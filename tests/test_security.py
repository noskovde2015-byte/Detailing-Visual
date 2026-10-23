import uuid

import pytest

from app.core.security import InvalidTokenError, TokenType, create_token, decode_token


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_token(user_id, TokenType.ACCESS)
    assert decode_token(token, TokenType.ACCESS) == user_id


def test_refresh_token_is_not_access_token() -> None:
    token = create_token(uuid.uuid4(), TokenType.REFRESH)
    with pytest.raises(InvalidTokenError):
        decode_token(token, TokenType.ACCESS)


def test_tampered_token_rejected() -> None:
    token = create_token(uuid.uuid4(), TokenType.ACCESS)
    with pytest.raises(InvalidTokenError):
        decode_token(token[:-2] + "xx", TokenType.ACCESS)
