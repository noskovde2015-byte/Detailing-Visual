import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.credit_grant import CreditGrant
from app.models.generation import Generation, GenerationStatus
from app.models.user import UserPlan


class GenerationLimitExceededError(Exception):
    def __init__(self, quota: "Quota") -> None:
        super().__init__("Лимит генераций исчерпан")
        self.quota = quota


@dataclass(frozen=True, slots=True)
class Quota:
    plan: str
    daily_limit: int
    daily_used: int
    bonus_balance: int
    window_hours: int
    resets_at: datetime | None

    @property
    def daily_remaining(self) -> int:
        return max(self.daily_limit - self.daily_used, 0)

    @property
    def remaining(self) -> int:
        return self.daily_remaining + self.bonus_balance

    @property
    def next_uses_bonus(self) -> bool:
        """Следующая генерация спишется с бонусов: дневной лимит уже исчерпан."""
        return self.daily_remaining == 0 and self.bonus_balance > 0


def plan_daily_limit(plan: str) -> int:
    config = settings.generation
    if plan == UserPlan.PRO:
        return config.pro_daily_limit
    return config.free_daily_limit


async def get_bonus_balance(session: AsyncSession, user_id: uuid.UUID) -> int:
    granted = await session.scalar(
        select(func.coalesce(func.sum(CreditGrant.amount), 0)).where(
            CreditGrant.user_id == user_id
        )
    )
    spent = await session.scalar(
        select(func.count()).where(
            Generation.user_id == user_id,
            Generation.used_bonus.is_(True),
            Generation.status != GenerationStatus.FAILED.value,
        )
    )
    return max(int(granted or 0) - int(spent or 0), 0)


async def get_quota(session: AsyncSession, user_id: uuid.UUID, plan: str) -> Quota:
    """Дневной лимит считается скользящим окном (последние N часов) только по
    генерациям, оплаченным дневной квотой. Бонусы тратятся, когда дневной лимит
    исчерпан, и не сгорают. Неудачные генерации не списываются ни там, ни там.
    """
    window = timedelta(hours=settings.generation.limit_window_hours)
    since = datetime.now(UTC) - window

    daily_used, oldest = (
        await session.execute(
            select(func.count(), func.min(Generation.created_at)).where(
                Generation.user_id == user_id,
                Generation.created_at > since,
                Generation.used_bonus.is_(False),
                Generation.status != GenerationStatus.FAILED.value,
            )
        )
    ).one()

    daily_limit = plan_daily_limit(plan)
    resets_at = (
        oldest + window if oldest is not None and daily_used >= daily_limit else None
    )
    return Quota(
        plan=plan,
        daily_limit=daily_limit,
        daily_used=daily_used,
        bonus_balance=await get_bonus_balance(session, user_id),
        window_hours=settings.generation.limit_window_hours,
        resets_at=resets_at,
    )
