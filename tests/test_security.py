import uuid

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_tampered_token_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    with pytest.raises(InvalidTokenError):
        decode_access_token(token[:-2] + "xx")


def test_token_of_other_type_rejected() -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "exp": 9999999999},
        settings.auth.secret_key.get_secret_value(),
        algorithm=settings.auth.algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_unsigned_token_rejected() -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": 9999999999},
        key=None,
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_refresh_tokens_are_unique_and_hashed() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()
    assert first != second
    assert len(hash_refresh_token(first)) == 64
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert first not in hash_refresh_token(first)
