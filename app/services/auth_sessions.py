import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_lifetime,
)
from app.models.refresh_session import RefreshSession

logger = logging.getLogger(__name__)

USER_AGENT_MAX_LENGTH = 512


class InvalidRefreshTokenError(Exception):
    """Refresh-токен не найден, просрочен или уже использован."""


@dataclass(frozen=True, slots=True)
class ClientInfo:
    user_agent: str | None
    ip_address: str | None


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    user_id: uuid.UUID
    token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _new_session(user_id: uuid.UUID, client: ClientInfo) -> tuple[RefreshSession, str]:
    token = generate_refresh_token()
    session_row = RefreshSession(
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        user_agent=(client.user_agent or "")[:USER_AGENT_MAX_LENGTH] or None,
        ip_address=client.ip_address,
        expires_at=_now() + refresh_token_lifetime(),
    )
    return session_row, token


async def create_refresh_session(
    session: AsyncSession, user_id: uuid.UUID, client: ClientInfo
) -> str:
    row, token = _new_session(user_id, client)
    session.add(row)
    await session.commit()
    return token


async def rotate_refresh_session(
    session: AsyncSession, token: str, client: ClientInfo
) -> IssuedRefreshToken:
    """Обменивает refresh-токен на новый. Старый становится недействительным.

    Повторное предъявление уже использованного токена означает, что токен
    утёк: им пользуются двое. В этом случае отзываются все сессии пользователя.
    Исключение — повтор в течение короткого окна (refresh_reuse_grace_seconds):
    так бывает, когда фронт отправил два /refresh параллельно.
    """
    now = _now()
    row = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_refresh_token(token))
        .with_for_update()
    )

    if row is None:
        raise InvalidRefreshTokenError

    if row.revoked_at is not None:
        grace = timedelta(seconds=settings.auth.refresh_reuse_grace_seconds)
        if now - row.revoked_at > grace:
            logger.warning(
                "Повторное использование refresh-токена, отзываю все сессии "
                "пользователя %s",
                row.user_id,
            )
            await _revoke_all(session, row.user_id, now)
            await session.commit()
        else:
            await session.rollback()
        raise InvalidRefreshTokenError

    if row.expires_at <= now:
        row.revoked_at = now
        await session.commit()
        raise InvalidRefreshTokenError

    row.revoked_at = now
    new_row, new_token = _new_session(row.user_id, client)
    session.add(new_row)
    await session.commit()
    return IssuedRefreshToken(user_id=row.user_id, token=new_token)


async def revoke_refresh_session(session: AsyncSession, token: str) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.token_hash == hash_refresh_token(token),
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    await session.commit()


async def revoke_all_user_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _revoke_all(session, user_id, _now())
    await session.commit()


async def _revoke_all(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
