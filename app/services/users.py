import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.credit_grant import CreditGrant, CreditGrantKind
from app.models.user import User

WELCOME_REASON = "Подарок при регистрации"


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
        user = User(
            id=uuid.uuid4(),
            google_sub=profile.sub,
            email=profile.email,
            name=profile.name,
        )
        session.add(user)
        # В той же транзакции, что и сам пользователь: либо оба, либо ничего.
        # Повторно не начислится: следующие входы идут по ветке else, а
        # уникальный индекс в базе страхует от гонки.
        welcome = settings.generation.welcome_credits
        if welcome > 0:
            # Связи (relationship) между моделями нет, поэтому SQLAlchemy не знает
            # порядок вставки: пользователь должен попасть в базу раньше
            # начисления, иначе нарушится внешний ключ.
            try:
                await session.flush()
            except IntegrityError:
                return await _resolve_conflict(session, profile)
            session.add(
                CreditGrant(
                    user_id=user.id,
                    kind=CreditGrantKind.WELCOME.value,
                    amount=welcome,
                    reason=WELCOME_REASON,
                )
            )
    else:
        user.email = profile.email
        user.name = profile.name

    try:
        await session.commit()
    except IntegrityError:
        return await _resolve_conflict(session, profile)

    await session.refresh(user)
    return user


async def _resolve_conflict(session: AsyncSession, profile: GoogleProfile) -> User:
    """Вставка нарушила уникальность. Два одновременных первых входа одного
    человека: запись (и подарок) уже создал параллельный запрос. Иначе почта
    занята другим google_sub."""
    await session.rollback()
    existing = await _get_by_google_sub(session, profile.sub)
    if existing is not None:
        return existing
    raise AccountConflictError from None
