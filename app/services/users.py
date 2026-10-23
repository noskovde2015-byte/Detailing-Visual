import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class AccountConflictError(Exception):
    """Почта уже привязана к другому Google-аккаунту."""


@dataclass(frozen=True, slots=True)
class GoogleProfile:
    sub: str
    email: str
    name: str | None


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def _get_by_google_sub(session: AsyncSession, sub: str) -> User | None:
    return await session.scalar(select(User).where(User.google_sub == sub))


async def get_or_create_google_user(
    session: AsyncSession, profile: GoogleProfile
) -> User:
    user = await _get_by_google_sub(session, profile.sub)

    if user is None:
        user = User(google_sub=profile.sub, email=profile.email, name=profile.name)
        session.add(user)
    else:
        user.email = profile.email
        user.name = profile.name

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Два одновременных первых входа одного человека: запись уже создал
        # параллельный запрос. Иначе почта занята другим google_sub.
        existing = await _get_by_google_sub(session, profile.sub)
        if existing is not None:
            return existing
        raise AccountConflictError from None

    await session.refresh(user)
    return user
