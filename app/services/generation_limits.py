import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.generation import Generation, GenerationStatus
from app.models.user import UserPlan


class DailyLimitExceededError(Exception):
    def __init__(self, quota: "Quota") -> None:
        super().__init__("Лимит генераций исчерпан")
        self.quota = quota


@dataclass(frozen=True, slots=True)
class Quota:
    plan: str
    limit: int
    used: int
    window_hours: int
    resets_at: datetime | None

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)


def plan_limit(plan: str) -> int:
    config = settings.generation
    if plan == UserPlan.PRO:
        return config.pro_daily_limit
    return config.free_daily_limit


async def get_quota(session: AsyncSession, user_id: uuid.UUID, plan: str) -> Quota:
    """Скользящее окно: считаются генерации за последние N часов.

    Неудачные (failed) генерации не списываются: пользователь не должен
    платить лимитом за наши сбои.
    """
    window = timedelta(hours=settings.generation.limit_window_hours)
    since = datetime.now(UTC) - window

    used, oldest = (
        await session.execute(
            select(func.count(), func.min(Generation.created_at)).where(
                Generation.user_id == user_id,
                Generation.created_at > since,
                Generation.status != GenerationStatus.FAILED.value,
            )
        )
    ).one()

    limit = plan_limit(plan)
    resets_at = oldest + window if oldest is not None and used >= limit else None
    return Quota(
        plan=plan,
        limit=limit,
        used=used,
        window_hours=settings.generation.limit_window_hours,
        resets_at=resets_at,
    )
