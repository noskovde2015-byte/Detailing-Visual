import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_BYTES = 48


class InvalidTokenError(Exception):
    """Access-токен отсутствует, просрочен, подделан или не того типа."""


def access_token_lifetime() -> timedelta:
    return timedelta(minutes=settings.auth.access_token_expire_minutes)


def refresh_token_lifetime() -> timedelta:
    return timedelta(days=settings.auth.refresh_token_expire_days)


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + access_token_lifetime(),
    }
    return jwt.encode(
        payload,
        settings.auth.secret_key.get_secret_value(),
        algorithm=settings.auth.algorithm,
    )


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.auth.secret_key.get_secret_value(),
            algorithms=[settings.auth.algorithm],
            options={"require": ["sub", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc

    if payload["type"] != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError

    try:
        return uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise InvalidTokenError from exc


def generate_refresh_token() -> str:
    """Непрозрачный случайный токен: вся информация о нём хранится в БД."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """В БД хранится только SHA-256: утечка базы не даёт рабочих токенов."""
    return hashlib.sha256(token.encode()).hexdigest()
