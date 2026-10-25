import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import GenerationImage
from app.services.storage import Storage

logger = logging.getLogger(__name__)


async def purge_generation_files(
    session: AsyncSession, storage: Storage, generation_id: uuid.UUID
) -> bool:
    """Удаляет все файлы генерации из хранилища и их записи из базы.

    Запись о файле удаляется только после того, как удалён сам файл. Если
    хранилище недоступно, запись остаётся, и уборщик повторит попытку позже.
    Возвращает True, если удалены все файлы.
    """
    images = (
        await session.scalars(
            select(GenerationImage).where(
                GenerationImage.generation_id == generation_id
            )
        )
    ).all()

    removed: list[uuid.UUID] = []
    for image in images:
        try:
            await storage.delete(image.storage_key)
        except Exception:
            logger.exception("Не удалось удалить файл %s", image.storage_key)
            continue
        removed.append(image.id)

    if removed:
        await session.execute(
            delete(GenerationImage).where(GenerationImage.id.in_(removed))
        )
        await session.commit()
    return len(removed) == len(images)


async def cleanup_storage(
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    *,
    failed_retention: timedelta,
    batch_size: int,
) -> int:
    """Удаляет файлы, которые больше не нужны:
    - удалённых пользователем генераций (если не получилось удалить сразу);
    - неудачных генераций старше failed_retention (фото нужны только на время
      разбора жалоб, а пользователю такая генерация ничего не показывает).

    Записи генераций остаются: по ним считаются лимиты и статистика.
    За один запуск обрабатывается не больше batch_size генераций, остальные
    подберёт следующий запуск. Возвращает число полностью очищенных генераций.
    """
    cutoff = datetime.now(UTC) - failed_retention
    has_files = exists().where(GenerationImage.generation_id == Generation.id)

    async with session_factory() as session:
        candidates = (
            await session.scalars(
                select(Generation.id)
                .where(
                    has_files,
                    or_(
                        Generation.deleted_at.is_not(None),
                        and_(
                            Generation.status == GenerationStatus.FAILED.value,
                            func.coalesce(Generation.finished_at, Generation.created_at)
                            < cutoff,
                        ),
                    ),
                )
                .order_by(Generation.created_at)
                .limit(batch_size)
            )
        ).all()

        purged = 0
        for generation_id in candidates:
            if await purge_generation_files(session, storage, generation_id):
                purged += 1

    if candidates:
        logger.info(
            "Уборка хранилища: очищено генераций %d из %d", purged, len(candidates)
        )
    return purged
