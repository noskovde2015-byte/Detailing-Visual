import logging
import uuid
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import GenerationImage, ImageRole
from app.models.user import User
from app.schemas.generation import GenerationParams, GenerationQuota, GenerationRead
from app.services.generation_limits import (
    GenerationLimitExceededError,
    Quota,
    get_quota,
)
from app.services.images import ProcessedImage
from app.services.storage import Storage, build_image_key

logger = logging.getLogger(__name__)


async def create_generation(
    session: AsyncSession,
    storage: Storage,
    user: User,
    params: GenerationParams,
    images: Mapping[ImageRole, ProcessedImage],
    model_name: str,
) -> Generation:
    """Создаёт генерацию в статусе pending вместе с входными файлами.

    Проверка лимита и вставка идут в одной транзакции под блокировкой строки
    пользователя: параллельные запросы одного пользователя выстраиваются в
    очередь и не могут вместе превысить лимит.
    """
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())

    quota = await get_quota(session, user.id, user.plan)
    if quota.remaining <= 0:
        await session.rollback()
        raise GenerationLimitExceededError(quota)

    generation = Generation(
        id=uuid.uuid4(),
        user_id=user.id,
        status=GenerationStatus.PENDING.value,
        params=params.model_dump(mode="json"),
        model=model_name,
        used_bonus=quota.next_uses_bonus,
    )
    session.add(generation)

    saved_keys: list[str] = []
    try:
        for role, image in images.items():
            key = build_image_key(generation.id, role, image.content_type)
            await storage.save(key, image.data, image.content_type)
            saved_keys.append(key)
            session.add(
                GenerationImage(
                    generation_id=generation.id,
                    role=role.value,
                    storage_key=key,
                    content_type=image.content_type,
                )
            )
        await session.commit()
    except BaseException:
        await session.rollback()
        for key in saved_keys:
            try:
                await storage.delete(key)
            except Exception:
                logger.exception("Не удалось удалить файл %s после отката", key)
        raise

    await session.refresh(generation, attribute_names=["images", "created_at"])
    return generation


async def get_user_generation(
    session: AsyncSession, user_id: uuid.UUID, generation_id: uuid.UUID
) -> Generation | None:
    return await session.scalar(
        select(Generation).where(
            Generation.id == generation_id,
            Generation.user_id == user_id,
        )
    )


async def get_generation(
    session: AsyncSession, generation_id: uuid.UUID
) -> Generation | None:
    return await session.get(Generation, generation_id)


async def list_user_generations(
    session: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Generation], int]:
    total = await session.scalar(
        select(func.count())
        .select_from(Generation)
        .where(Generation.user_id == user_id)
    )
    rows = await session.scalars(
        select(Generation)
        .where(Generation.user_id == user_id)
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


def image_url(generation_id: uuid.UUID, role: ImageRole, *, admin: bool = False) -> str:
    prefix = settings.prefix
    section = (
        f"{prefix.admin_prefix}{prefix.generations_prefix}"
        if admin
        else prefix.generations_prefix
    )
    return f"{prefix.api_prefix}{section}/{generation_id}/images/{role.value}"


def to_read(generation: Generation, *, admin: bool = False) -> GenerationRead:
    roles = {image.role for image in generation.images}
    result_url = (
        image_url(generation.id, ImageRole.RESULT, admin=admin)
        if generation.status == GenerationStatus.DONE and ImageRole.RESULT in roles
        else None
    )
    input_roles = [
        role.value for role in ImageRole if role != ImageRole.RESULT and role in roles
    ]
    return GenerationRead(
        id=generation.id,
        status=generation.status,
        params=GenerationParams.model_validate(generation.params),
        input_roles=input_roles,
        used_bonus=generation.used_bonus,
        error=generation.error,
        created_at=generation.created_at,
        started_at=generation.started_at,
        finished_at=generation.finished_at,
        result_url=result_url,
    )


def quota_to_schema(quota: Quota) -> GenerationQuota:
    return GenerationQuota(
        plan=quota.plan,
        daily_limit=quota.daily_limit,
        daily_used=quota.daily_used,
        daily_remaining=quota.daily_remaining,
        bonus_remaining=quota.bonus_balance,
        remaining=quota.remaining,
        window_hours=quota.window_hours,
        resets_at=quota.resets_at,
    )
