import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.credit_grant import CreditGrant, CreditGrantKind
from app.models.user import User
from app.services.balance import InsufficientBalanceError, get_balance, lock_user


@dataclass(frozen=True, slots=True)
class GrantRecord:
    grant: CreditGrant
    author_email: str | None
    author_name: str | None


async def grant_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: int,
    reason: str | None,
    granted_by_id: uuid.UUID | None,
    kind: CreditGrantKind = CreditGrantKind.ADMIN,
) -> CreditGrant:
    """Начисляет (amount > 0) или списывает (amount < 0) генерации.

    Списать больше, чем есть на балансе, нельзя.
    """
    await lock_user(session, user_id)

    if amount < 0:
        balance = await get_balance(session, user_id)
        if balance + amount < 0:
            await session.rollback()
            raise InsufficientBalanceError(balance)

    grant = CreditGrant(
        user_id=user_id,
        kind=kind.value,
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
) -> tuple[list[GrantRecord], int]:
    total = await session.scalar(
        select(func.count())
        .select_from(CreditGrant)
        .where(CreditGrant.user_id == user_id)
    )
    author = aliased(User)
    rows = await session.execute(
        select(CreditGrant, author.email, author.name)
        .outerjoin(author, author.id == CreditGrant.granted_by_id)
        .where(CreditGrant.user_id == user_id)
        .order_by(CreditGrant.created_at.desc(), CreditGrant.id.desc())
        .limit(limit)
        .offset(offset)
    )
    records = [
        GrantRecord(grant=grant, author_email=email, author_name=name)
        for grant, email, name in rows.all()
    ]
    return records, total or 0
