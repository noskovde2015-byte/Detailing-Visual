import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_grant import CreditGrant
from app.models.generation import Generation, GenerationStatus
from app.models.user import User, UserPlan
from app.schemas.admin import AdminStats, AdminUserRead
from app.services.auth_sessions import revoke_all_user_sessions

SEARCH_MAX_LENGTH = 100


class AdminActionError(Exception):
    """Действие запрещено (например, заблокировать самого себя)."""


def _generations_total():
    return (
        select(func.count())
        .where(Generation.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


def _bonus_remaining():
    granted = (
        select(func.coalesce(func.sum(CreditGrant.amount), 0))
        .where(CreditGrant.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    spent = (
        select(func.count())
        .where(
            Generation.user_id == User.id,
            Generation.used_bonus.is_(True),
            Generation.status != GenerationStatus.FAILED.value,
        )
        .correlate(User)
        .scalar_subquery()
    )
    return func.greatest(granted - spent, 0)


def _users_query():
    return select(
        User,
        _generations_total().label("generations_total"),
        _bonus_remaining().label("bonus_remaining"),
    )


def _to_read(user: User, generations_total: int, bonus_remaining: int) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        plan=user.plan,
        is_admin=user.is_admin,
        is_blocked=user.is_blocked,
        created_at=user.created_at,
        generations_total=generations_total,
        bonus_remaining=bonus_remaining,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    session: AsyncSession, search: str | None, limit: int, offset: int
) -> tuple[list[AdminUserRead], int]:
    conditions = []
    if search:
        pattern = f"%{_escape_like(search.strip()[:SEARCH_MAX_LENGTH])}%"
        conditions.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.name.ilike(pattern, escape="\\"),
            )
        )

    total = await session.scalar(
        select(func.count()).select_from(User).where(*conditions)
    )
    rows = await session.execute(
        _users_query()
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_to_read(*row) for row in rows.all()], total or 0


async def get_admin_user(
    session: AsyncSession, user_id: uuid.UUID
) -> AdminUserRead | None:
    row = (await session.execute(_users_query().where(User.id == user_id))).first()
    return _to_read(*row) if row else None


async def update_user(
    session: AsyncSession,
    admin: User,
    user: User,
    *,
    plan: UserPlan | None,
    is_blocked: bool | None,
) -> None:
    if is_blocked and user.id == admin.id:
        raise AdminActionError("Нельзя заблокировать самого себя")
    if is_blocked and user.is_admin:
        raise AdminActionError("Нельзя заблокировать администратора")

    if plan is not None:
        user.plan = plan.value
    if is_blocked is not None:
        user.is_blocked = is_blocked
    await session.commit()

    if is_blocked:
        await revoke_all_user_sessions(session, user.id)


async def get_stats(session: AsyncSession) -> AdminStats:
    since = datetime.now(UTC) - timedelta(hours=24)

    users_total, users_new, users_blocked = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(User.created_at > since),
                func.count().filter(User.is_blocked.is_(True)),
            ).select_from(User)
        )
    ).one()

    generations_total, generations_recent, bonus_recent = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Generation.created_at > since),
                func.count().filter(
                    Generation.created_at > since, Generation.used_bonus.is_(True)
                ),
            ).select_from(Generation)
        )
    ).one()

    by_status = dict(
        (
            await session.execute(
                select(Generation.status, func.count())
                .where(Generation.created_at > since)
                .group_by(Generation.status)
            )
        ).all()
    )

    return AdminStats(
        users_total=users_total,
        users_new_24h=users_new,
        users_blocked=users_blocked,
        generations_total=generations_total,
        generations_24h=generations_recent,
        generations_24h_by_status={
            status.value: by_status.get(status.value, 0) for status in GenerationStatus
        },
        bonus_generations_24h=bonus_recent,
    )
