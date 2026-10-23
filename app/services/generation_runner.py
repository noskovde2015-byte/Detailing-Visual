import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import GenerationImage, ImageRole
from app.schemas.generation import GenerationParams
from app.services.image_generator import (
    ImageData,
    ImageGenerationError,
    ImageGenerator,
)
from app.services.prompt_builder import build_prompt, ordered_roles
from app.services.storage import Storage, build_image_key

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Не удалось выполнить генерацию. Лимит не списан, попробуйте ещё раз."
INTERRUPTED_ERROR = "Генерация была прервана. Лимит не списан, попробуйте ещё раз."


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


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    generation_id: uuid.UUID,
    message: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Generation)
            .where(Generation.id == generation_id)
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
) -> None:
    """Выполняет одну генерацию. Безопасно вызывать повторно для той же задачи.

    Не бросает исключений наружу: любой исход фиксируется в статусе генерации.
    """
    result_key: str | None = None
    try:
        async with session_factory() as session:
            if not await _claim(session, generation_id):
                logger.info("Генерация %s уже взята или завершена", generation_id)
                return

            generation = await session.get(Generation, generation_id)
            if generation is None:
                return

            params = GenerationParams.model_validate(generation.params)
            inputs = {
                ImageRole(image.role): image
                for image in generation.images
                if image.role != ImageRole.RESULT
            }
            roles = ordered_roles(inputs.keys())
            images = [
                ImageData(
                    data=await storage.read(inputs[role].storage_key),
                    mime_type=inputs[role].content_type,
                )
                for role in roles
            ]

            prompt = build_prompt(params, roles)
            result = await generator.generate(prompt, images)

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

    except ImageGenerationError as exc:
        logger.warning("Генерация %s не удалась: %s", generation_id, exc)
        await _cleanup(storage, result_key)
        await _mark_failed(session_factory, generation_id, str(exc))
    except Exception:
        logger.exception("Непредвиденная ошибка в генерации %s", generation_id)
        await _cleanup(storage, result_key)
        await _mark_failed(session_factory, generation_id, GENERIC_ERROR)


async def _cleanup(storage: Storage, key: str | None) -> None:
    if key is None:
        return
    try:
        await storage.delete(key)
    except Exception:
        logger.exception("Не удалось удалить файл результата %s", key)


async def fail_stale_generations(
    session_factory: async_sessionmaker[AsyncSession], older_than: timedelta
) -> int:
    """Помечает failed задачи, которые зависли (например, сервер перезапустили
    посреди генерации). Вызывается при старте приложения."""
    threshold = _now() - older_than
    async with session_factory() as session:
        result = await session.execute(
            update(Generation)
            .where(
                or_(
                    (Generation.status == GenerationStatus.PENDING.value)
                    & (Generation.created_at < threshold),
                    (Generation.status == GenerationStatus.PROCESSING.value)
                    & (Generation.started_at < threshold),
                )
            )
            .values(
                status=GenerationStatus.FAILED.value,
                error=INTERRUPTED_ERROR,
                finished_at=_now(),
            )
            .returning(Generation.id)
        )
        failed_ids = list(result.scalars())
        await session.commit()

    if failed_ids:
        logger.warning("Помечено зависших генераций: %d", len(failed_ids))
    return len(failed_ids)
