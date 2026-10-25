import asyncio
import enum
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import GenerationImage, ImageRole
from app.schemas.generation import GenerationParams
from app.services.image_generator import (
    GenerationTemporaryError,
    ImageData,
    ImageGenerationError,
    ImageGenerator,
)
from app.services.model_request import build_model_request
from app.services.storage import Storage, build_image_key

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Не удалось выполнить генерацию. Лимит не списан, попробуйте ещё раз."
INTERRUPTED_ERROR = "Генерация была прервана. Лимит не списан, попробуйте ещё раз."
TIMEOUT_ERROR = (
    "Генерация заняла слишком много времени. Лимит не списан, попробуйте ещё раз."
)
QUEUE_UNAVAILABLE_ERROR = (
    "Сервис генерации временно недоступен. Лимит не списан, попробуйте позже."
)


class GenerationOutcome(enum.StrEnum):
    DONE = "done"
    FAILED = "failed"
    RETRY = "retry"
    """Временный сбой: задача возвращена в pending, её нужно перезапустить позже."""
    SKIPPED = "skipped"
    """Задачу уже взял другой исполнитель или она завершена."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _claim(session: AsyncSession, generation_id: uuid.UUID) -> bool:
    """Атомарно переводит pending → processing.

    Если два исполнителя получили одну задачу, выполнит её только один:
    второй не найдёт строку в статусе pending.
    """
    claimed = await session.scalar(
        update(Generation)
        .where(
            Generation.id == generation_id,
            Generation.status == GenerationStatus.PENDING.value,
        )
        .values(status=GenerationStatus.PROCESSING.value, started_at=_now())
        .returning(Generation.id)
    )
    await session.commit()
    return claimed is not None


async def _release(
    session_factory: async_sessionmaker[AsyncSession], generation_id: uuid.UUID
) -> None:
    """Возвращает взятую задачу в pending, чтобы её мог выполнить следующий запуск."""
    async with session_factory() as session:
        await session.execute(
            update(Generation)
            .where(
                Generation.id == generation_id,
                Generation.status == GenerationStatus.PROCESSING.value,
            )
            .values(status=GenerationStatus.PENDING.value, started_at=None)
        )
        await session.commit()


async def mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    generation_id: uuid.UUID,
    message: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Generation)
            .where(
                Generation.id == generation_id,
                Generation.status.in_(
                    (GenerationStatus.PENDING.value, GenerationStatus.PROCESSING.value)
                ),
            )
            .values(
                status=GenerationStatus.FAILED.value,
                error=message,
                finished_at=_now(),
            )
        )
        await session.commit()


async def run_generation(
    generation_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    generator: ImageGenerator,
    storage: Storage,
    timeout_seconds: float | None = None,
    allow_retry: bool = False,
) -> GenerationOutcome:
    """Выполняет одну генерацию. Безопасно вызывать повторно для той же задачи.

    Исход фиксируется в статусе генерации и возвращается вызывающему.
    allow_retry: при временном сбое вернуть задачу в pending (исход RETRY)
    вместо того, чтобы сразу пометить её неудачной. Повтор планирует вызывающий.
    При отмене (остановка воркера) задача возвращается в pending, а отмена
    пробрасывается дальше: очередь запустит её снова.
    """
    claimed = False
    result_key: str | None = None
    try:
        async with session_factory() as session:
            claimed = await _claim(session, generation_id)
            if not claimed:
                logger.info("Генерация %s уже взята или завершена", generation_id)
                return GenerationOutcome.SKIPPED

            generation = await session.get(Generation, generation_id)
            if generation is None:
                return GenerationOutcome.SKIPPED

            params = GenerationParams.model_validate(generation.params)
            uploaded = {
                ImageRole(image.role): ImageData(
                    data=await storage.read(image.storage_key),
                    mime_type=image.content_type,
                )
                for image in generation.images
                if image.role != ImageRole.RESULT
            }

            request = build_model_request(params, uploaded)
            async with asyncio.timeout(timeout_seconds):
                result = await generator.generate(request.prompt, request.images)

            result_key = build_image_key(
                generation_id, ImageRole.RESULT, result.mime_type
            )
            await storage.save(result_key, result.data, result.mime_type)

            session.add(
                GenerationImage(
                    generation_id=generation_id,
                    role=ImageRole.RESULT.value,
                    storage_key=result_key,
                    content_type=result.mime_type,
                )
            )
            generation.status = GenerationStatus.DONE.value
            generation.finished_at = _now()
            generation.error = None
            await session.commit()
            logger.info("Генерация %s завершена", generation_id)
            return GenerationOutcome.DONE

    except asyncio.CancelledError:
        if claimed:
            logger.warning("Генерация %s отменена, возвращаю в очередь", generation_id)
            await asyncio.shield(_cleanup(storage, result_key))
            await asyncio.shield(_release(session_factory, generation_id))
        raise
    except GenerationTemporaryError as exc:
        await _cleanup(storage, result_key)
        if allow_retry:
            logger.warning("Генерация %s: временный сбой, повторим", generation_id)
            await _release(session_factory, generation_id)
            return GenerationOutcome.RETRY
        logger.warning("Генерация %s не удалась: %s", generation_id, exc)
        await mark_failed(session_factory, generation_id, str(exc))
        return GenerationOutcome.FAILED
    except ImageGenerationError as exc:
        logger.warning("Генерация %s не удалась: %s", generation_id, exc)
        await _cleanup(storage, result_key)
        await mark_failed(session_factory, generation_id, str(exc))
        return GenerationOutcome.FAILED
    except TimeoutError:
        logger.warning(
            "Генерация %s не уложилась в %s с", generation_id, timeout_seconds
        )
        await _cleanup(storage, result_key)
        await mark_failed(session_factory, generation_id, TIMEOUT_ERROR)
        return GenerationOutcome.FAILED
    except Exception:
        logger.exception("Непредвиденная ошибка в генерации %s", generation_id)
        await _cleanup(storage, result_key)
        await mark_failed(session_factory, generation_id, GENERIC_ERROR)
        return GenerationOutcome.FAILED


async def _cleanup(storage: Storage, key: str | None) -> None:
    if key is None:
        return
    try:
        await storage.delete(key)
    except Exception:
        logger.exception("Не удалось удалить файл результата %s", key)


async def fail_stale_generations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pending_older_than: timedelta,
    processing_older_than: timedelta,
) -> int:
    """Помечает failed задачи, которые зависли: исполнитель упал посреди работы
    или задача потерялась по пути в очередь.

    Пороги разные: pending честно ждёт своей очереди, когда воркер загружен,
    а processing дольше таймаута задачи означает, что исполнитель умер.
    """
    now = _now()
    async with session_factory() as session:
        result = await session.execute(
            update(Generation)
            .where(
                or_(
                    (Generation.status == GenerationStatus.PENDING.value)
                    & (Generation.created_at < now - pending_older_than),
                    (Generation.status == GenerationStatus.PROCESSING.value)
                    & (Generation.started_at < now - processing_older_than),
                )
            )
            .values(
                status=GenerationStatus.FAILED.value,
                error=INTERRUPTED_ERROR,
                finished_at=now,
            )
            .returning(Generation.id)
        )
        failed_ids = list(result.scalars())
        await session.commit()

    if failed_ids:
        logger.warning("Помечено зависших генераций: %d", len(failed_ids))
    return len(failed_ids)
