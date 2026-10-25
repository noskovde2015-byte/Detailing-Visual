import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_grant import CreditGrant
from app.models.user import User
from app.services.generation_limits import get_bonus_balance


class InsufficientBonusError(Exception):
    def __init__(self, balance: int) -> None:
        super().__init__(f"Нельзя списать больше остатка ({balance})")
        self.balance = balance


async def grant_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: int,
    reason: str | None,
    granted_by_id: uuid.UUID | None,
) -> CreditGrant:
    """Начисляет (amount > 0) или списывает (amount < 0) бонусные генерации.

    Блокировка строки пользователя та же, что при создании генерации: списание
    и одновременная генерация не уведут баланс в минус.
    """
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())

    if amount < 0:
        balance = await get_bonus_balance(session, user_id)
        if balance + amount < 0:
            await session.rollback()
            raise InsufficientBonusError(balance)

    grant = CreditGrant(
        user_id=user_id,
        amount=amount,
        reason=reason,
        granted_by_id=granted_by_id,
    )
    session.add(grant)
    await session.commit()
    await session.refresh(grant)
    return grant


async def list_grants(
    session: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[CreditGrant], int]:
    total = await session.scalar(
        select(func.count())
        .select_from(CreditGrant)
        .where(CreditGrant.user_id == user_id)
    )
    rows = await session.scalars(
        select(CreditGrant)
        .where(CreditGrant.user_id == user_id)
        .order_by(CreditGrant.created_at.desc(), CreditGrant.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0
