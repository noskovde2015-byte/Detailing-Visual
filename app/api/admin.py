import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentAdmin, SessionDep
from app.api.generations import IMAGE_RESPONSES, generation_image_response
from app.core.config import settings
from app.models.generation_image import ImageRole
from app.models.user import User
from app.schemas.admin import (
    AdminStats,
    AdminUserDetail,
    AdminUserList,
    AdminUserRead,
    AdminUserUpdate,
    CreditGrantCreate,
    CreditGrantList,
    CreditGrantRead,
)
from app.schemas.generation import GenerationList, GenerationRead
from app.services.admin import (
    AdminActionError,
    get_admin_user,
    get_stats,
    list_users,
    update_user,
)
from app.services.credits import InsufficientBonusError, grant_credits, list_grants
from app.services.generation_limits import get_quota
from app.services.generations import (
    get_generation,
    list_user_generations,
    quota_to_schema,
    to_read,
)
from app.services.users import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.prefix.admin_prefix, tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _load_user(session: SessionDep, user_id: uuid.UUID) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


async def _user_read(session: SessionDep, user_id: uuid.UUID) -> AdminUserRead:
    user = await get_admin_user(session, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


@router.get("/stats", response_model=AdminStats, summary="Сводка")
async def stats(admin: CurrentAdmin, session: SessionDep) -> AdminStats:
    return await get_stats(session)


@router.get("/users", response_model=AdminUserList, summary="Пользователи")
async def users(
    admin: CurrentAdmin,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> AdminUserList:
    items, total = await list_users(session, search, limit, offset)
    return AdminUserList(items=items, total=total, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=AdminUserDetail, summary="Пользователь")
async def user_detail(
    user_id: uuid.UUID, admin: CurrentAdmin, session: SessionDep
) -> AdminUserDetail:
    user = await _load_user(session, user_id)
    quota = await get_quota(session, user.id, user.plan)
    return AdminUserDetail(
        user=await _user_read(session, user_id), quota=quota_to_schema(quota)
    )


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserRead,
    summary="Сменить план или заблокировать",
)
async def user_update(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    admin: CurrentAdmin,
    session: SessionDep,
) -> AdminUserRead:
    user = await _load_user(session, user_id)
    try:
        await update_user(
            session, admin, user, plan=payload.plan, is_blocked=payload.is_blocked
        )
    except AdminActionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None

    logger.info(
        "Админ %s изменил пользователя %s: %s",
        admin.email,
        user_id,
        payload.model_dump(exclude_none=True),
    )
    return await _user_read(session, user_id)


@router.get(
    "/users/{user_id}/credits",
    response_model=CreditGrantList,
    summary="История бонусов",
)
async def credits(
    user_id: uuid.UUID,
    admin: CurrentAdmin,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> CreditGrantList:
    await _load_user(session, user_id)
    rows, total = await list_grants(session, user_id, limit, offset)
    return CreditGrantList(
        items=[CreditGrantRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users/{user_id}/credits",
    response_model=CreditGrantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Выдать или списать бонусные генерации",
)
async def credits_grant(
    user_id: uuid.UUID,
    payload: CreditGrantCreate,
    admin: CurrentAdmin,
    session: SessionDep,
) -> CreditGrantRead:
    await _load_user(session, user_id)
    admin_id, admin_email = admin.id, admin.email
    try:
        grant = await grant_credits(
            session, user_id, payload.amount, payload.reason, admin_id
        )
    except InsufficientBonusError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None

    logger.info(
        "Админ %s начислил %+d генераций пользователю %s (%s)",
        admin_email,
        payload.amount,
        user_id,
        payload.reason or "без причины",
    )
    return CreditGrantRead.model_validate(grant)


@router.get(
    "/users/{user_id}/generations",
    response_model=GenerationList,
    summary="Генерации пользователя",
)
async def user_generations(
    user_id: uuid.UUID,
    admin: CurrentAdmin,
    session: SessionDep,
    limit: Limit = 20,
    offset: Offset = 0,
) -> GenerationList:
    await _load_user(session, user_id)
    rows, total = await list_user_generations(session, user_id, limit, offset)
    return GenerationList(
        items=[to_read(row, admin=True) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    f"{settings.prefix.generations_prefix}/{{generation_id}}",
    response_model=GenerationRead,
    summary="Любая генерация",
)
async def generation_detail(
    generation_id: uuid.UUID, admin: CurrentAdmin, session: SessionDep
) -> GenerationRead:
    generation = await get_generation(session, generation_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Генерация не найдена")
    return to_read(generation, admin=True)


@router.get(
    f"{settings.prefix.generations_prefix}/{{generation_id}}/images/{{role}}",
    response_class=Response,
    responses=IMAGE_RESPONSES,
    summary="Изображение любой генерации",
)
async def generation_image(
    generation_id: uuid.UUID,
    role: ImageRole,
    admin: CurrentAdmin,
    session: SessionDep,
    download: bool = False,
) -> Response:
    generation = await get_generation(session, generation_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Генерация не найдена")
    return await generation_image_response(generation, role, download=download)
