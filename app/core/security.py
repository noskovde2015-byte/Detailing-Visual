import enum
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


class TokenType(enum.StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class InvalidTokenError(Exception):
    """Токен отсутствует, просрочен, подделан или не того типа."""


def _lifetime(token_type: TokenType) -> timedelta:
    if token_type is TokenType.ACCESS:
        return timedelta(minutes=settings.auth.access_token_expire_minutes)
    return timedelta(days=settings.auth.refresh_token_expire_days)


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + _lifetime(token_type),
    }
    return jwt.encode(
        payload,
        settings.auth.secret_key.get_secret_value(),
        algorithm=settings.auth.algorithm,
    )


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.auth.secret_key.get_secret_value(),
            algorithms=[settings.auth.algorithm],
            options={"require": ["sub", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc

    if payload["type"] != expected_type.value:
        raise InvalidTokenError

    try:
        return uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise InvalidTokenError from exc


def token_max_age(token_type: TokenType) -> int:
    return int(_lifetime(token_type).total_seconds())
