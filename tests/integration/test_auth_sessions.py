from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_refresh_token
from app.db.db_helper import db_helper
from app.models.refresh_session import RefreshSession
from app.services.auth_sessions import (
    ClientInfo,
    InvalidRefreshTokenError,
    create_refresh_session,
    revoke_refresh_session,
    rotate_refresh_session,
)
from tests.integration.conftest import login

pytestmark = pytest.mark.anyio

CLIENT = ClientInfo(user_agent="pytest", ip_address="127.0.0.1")


async def _active_sessions(user_id) -> int:
    async with db_helper.session_factory() as session:
        return await session.scalar(
            select(func.count()).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        )


async def _backdate_revocation(token: str, seconds: int) -> None:
    async with db_helper.session_factory() as session:
        row = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(token)
            )
        )
        row.revoked_at = datetime.now(UTC) - timedelta(seconds=seconds)
        await session.commit()


async def test_rotation_issues_new_token_and_revokes_old(make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        old = await create_refresh_session(session, user.id, CLIENT)
        issued = await rotate_refresh_session(session, old, CLIENT)

    assert issued.user_id == user.id
    assert issued.token != old
    assert await _active_sessions(user.id) == 1


async def test_reuse_after_grace_revokes_all_sessions(make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        other_device = await create_refresh_session(session, user.id, CLIENT)
        stolen = await create_refresh_session(session, user.id, CLIENT)
        await rotate_refresh_session(session, stolen, CLIENT)

    await _backdate_revocation(stolen, settings.auth.refresh_reuse_grace_seconds + 5)

    async with db_helper.session_factory() as session:
        with pytest.raises(InvalidRefreshTokenError):
            await rotate_refresh_session(session, stolen, CLIENT)

    assert await _active_sessions(user.id) == 0
    async with db_helper.session_factory() as session:
        with pytest.raises(InvalidRefreshTokenError):
            await rotate_refresh_session(session, other_device, CLIENT)


async def test_parallel_refresh_within_grace_keeps_sessions(make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        token = await create_refresh_session(session, user.id, CLIENT)
        await rotate_refresh_session(session, token, CLIENT)
        with pytest.raises(InvalidRefreshTokenError):
            await rotate_refresh_session(session, token, CLIENT)

    assert await _active_sessions(user.id) == 1


async def test_expired_token_rejected(make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        token = await create_refresh_session(session, user.id, CLIENT)
        row = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(token)
            )
        )
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            await rotate_refresh_session(session, token, CLIENT)


async def test_revoked_token_cannot_refresh(make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        token = await create_refresh_session(session, user.id, CLIENT)
        await revoke_refresh_session(session, token)
    assert await _active_sessions(user.id) == 0


async def test_refresh_endpoint_rotates_cookie(client: AsyncClient, make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        token = await create_refresh_session(session, user.id, CLIENT)

    client.cookies.set(settings.auth.refresh_cookie_name, token, path="/api/auth")
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 204
    new_token = response.cookies.get(settings.auth.refresh_cookie_name)
    assert new_token and new_token != token
    assert response.cookies.get(settings.auth.access_cookie_name)


async def test_refresh_endpoint_without_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 401


async def test_logout_all(client: AsyncClient, make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        await create_refresh_session(session, user.id, CLIENT)
        await create_refresh_session(session, user.id, CLIENT)

    login(client, user)
    response = await client.post("/api/auth/logout-all")
    assert response.status_code == 204
    assert await _active_sessions(user.id) == 0
