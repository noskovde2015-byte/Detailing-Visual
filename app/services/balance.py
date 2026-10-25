import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_grant import CreditGrant
from app.models.generation import Generation, GenerationStatus
from app.models.user import User

INSUFFICIENT_BALANCE_MESSAGE = "Недостаточно генераций на балансе"


class InsufficientBalanceError(Exception):
    def __init__(self, balance: int) -> None:
        super().__init__(INSUFFICIENT_BALANCE_MESSAGE)
        self.balance = balance


def charged_generation() -> ColumnElement[bool]:
    """Генерация, которая занимает единицу баланса.

    pending и processing тоже занимают: иначе можно запустить десять генераций
    при балансе в одну. Неудачная генерация единицу возвращает.
    """
    return Generation.charged.is_(True) & (
        Generation.status != GenerationStatus.FAILED.value
    )


def balance_of(user_id: ColumnElement[uuid.UUID]) -> ColumnElement[int]:
    """Баланс пользователя как SQL-выражение: для списков в админке."""
    granted = (
        select(func.coalesce(func.sum(CreditGrant.amount), 0))
        .where(CreditGrant.user_id == user_id)
        .scalar_subquery()
    )
    spent = (
        select(func.count())
        .where(Generation.user_id == user_id, charged_generation())
        .scalar_subquery()
    )
    return func.greatest(granted - spent, 0)


async def get_balance(session: AsyncSession, user_id: uuid.UUID) -> int:
    granted = await session.scalar(
        select(func.coalesce(func.sum(CreditGrant.amount), 0)).where(
            CreditGrant.user_id == user_id
        )
    )
    spent = await session.scalar(
        select(func.count()).where(Generation.user_id == user_id, charged_generation())
    )
    return max(int(granted or 0) - int(spent or 0), 0)


async def lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Блокирует строку пользователя до конца транзакции.

    Все операции, меняющие баланс (создание генерации, начисление, списание),
    берут эту блокировку первыми, поэтому параллельные запросы одного
    пользователя выстраиваются в очередь и не уводят баланс в минус.
    """
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
