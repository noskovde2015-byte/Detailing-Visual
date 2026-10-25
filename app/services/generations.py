import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import INPUT_ROLES, GenerationImage, ImageRole
from app.models.user import User
from app.schemas.generation import GenerationParams, GenerationRead
from app.services.balance import InsufficientBalanceError, get_balance, lock_user
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

    Генерация сразу занимает единицу баланса. Проверка баланса и вставка идут
    в одной транзакции под блокировкой строки пользователя: параллельные
    запросы выстраиваются в очередь и не могут потратить больше, чем есть.
    Если генерация не удастся, единица вернётся (failed не считается).
    """
    await lock_user(session, user.id)

    balance = await get_balance(session, user.id)
    if balance <= 0:
        await session.rollback()
        raise InsufficientBalanceError(balance)

    generation = Generation(
        id=uuid.uuid4(),
        user_id=user.id,
        status=GenerationStatus.PENDING.value,
        params=params.model_dump(mode="json"),
        model=model_name,
        charged=True,
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


class GenerationNotDeletableError(Exception):
    """Генерация ещё выполняется: удалять её нельзя, воркер запишет результат."""


async def get_user_generation(
    session: AsyncSession, user_id: uuid.UUID, generation_id: uuid.UUID
) -> Generation | None:
    """Генерация пользователя. Удалённые для него не существуют."""
    return await session.scalar(
        select(Generation).where(
            Generation.id == generation_id,
            Generation.user_id == user_id,
            Generation.deleted_at.is_(None),
        )
    )


async def soft_delete_generation(session: AsyncSession, generation: Generation) -> None:
    """Помечает генерацию удалённой. Строка остаётся, чтобы удаление не возвращало
    генерацию на баланс: иначе можно генерировать бесконечно, удаляя старые.
    Файлы удаляет вызывающий (cleanup.purge_generation_files)."""
    if generation.status in (
        GenerationStatus.PENDING.value,
        GenerationStatus.PROCESSING.value,
    ):
        raise GenerationNotDeletableError
    generation.deleted_at = datetime.now(UTC)
    await session.commit()


async def get_generation(
    session: AsyncSession, generation_id: uuid.UUID
) -> Generation | None:
    return await session.get(Generation, generation_id)


async def list_user_generations(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
    *,
    status: GenerationStatus | None = None,
    include_deleted: bool = False,
) -> tuple[list[Generation], int]:
    conditions = [Generation.user_id == user_id]
    if status is not None:
        conditions.append(Generation.status == status.value)
    if not include_deleted:
        conditions.append(Generation.deleted_at.is_(None))

    total = await session.scalar(
        select(func.count()).select_from(Generation).where(*conditions)
    )
    rows = await session.scalars(
        select(Generation)
        .where(*conditions)
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
    is_done = generation.status == GenerationStatus.DONE

    def url_for(role: ImageRole) -> str | None:
        if is_done and role in roles:
            return image_url(generation.id, role, admin=admin)
        return None

    input_roles = [role.value for role in ImageRole if role in INPUT_ROLES & roles]
    return GenerationRead(
        id=generation.id,
        status=generation.status,
        params=GenerationParams.model_validate(generation.params),
        input_roles=input_roles,
        error=generation.error,
        created_at=generation.created_at,
        started_at=generation.started_at,
        finished_at=generation.finished_at,
        deleted_at=generation.deleted_at,
        result_url=url_for(ImageRole.RESULT),
        preview_url=url_for(ImageRole.PREVIEW),
    )
