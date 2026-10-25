import asyncio
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.db.db_helper import db_helper
from app.models.credit_grant import CreditGrant, CreditGrantKind
from app.services.balance import get_balance
from app.services.users import GoogleProfile, get_or_create_google_user
from tests.integration.conftest import image_file, login

pytestmark = pytest.mark.anyio


def _profile(sub: str = "google-sub-1") -> GoogleProfile:
    return GoogleProfile(sub=sub, email=f"{sub}@example.com", name="Новый")


async def _welcome_grants(user_id) -> int:
    async with db_helper.session_factory() as session:
        return await session.scalar(
            select(func.count()).where(
                CreditGrant.user_id == user_id,
                CreditGrant.kind == CreditGrantKind.WELCOME.value,
            )
        )


async def test_first_login_gets_one_welcome_generation(db: None) -> None:
    async with db_helper.session_factory() as session:
        user = await get_or_create_google_user(session, _profile())
        assert (
            await get_balance(session, user.id)
            == settings.generation.welcome_credits
            == 1
        )

    # Повторный вход того же человека ничего не начисляет.
    async with db_helper.session_factory() as session:
        again = await get_or_create_google_user(session, _profile())
        assert again.id == user.id
        assert await get_balance(session, user.id) == 1

    assert await _welcome_grants(user.id) == 1


async def test_welcome_can_be_disabled(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.generation, "welcome_credits", 0)
    async with db_helper.session_factory() as session:
        user = await get_or_create_google_user(session, _profile("no-gift"))
        assert await get_balance(session, user.id) == 0
    assert await _welcome_grants(user.id) == 0


async def test_concurrent_first_logins_create_one_user_and_one_gift(db: None) -> None:
    async def login_once():
        async with db_helper.session_factory() as session:
            return await get_or_create_google_user(session, _profile("racer"))

    users = await asyncio.gather(*(login_once() for _ in range(5)))
    assert len({user.id for user in users}) == 1
    assert await _welcome_grants(users[0].id) == 1


async def test_me_returns_balance_and_admin_flag(
    client: AsyncClient, make_user
) -> None:
    login(client, await make_user(is_admin=True, balance=7))
    me = (await client.get("/api/users/me")).json()
    assert me["balance"] == 7
    assert me["is_admin"] is True
    assert "plan" not in me


async def test_parallel_requests_cannot_overspend(
    client: AsyncClient, make_user
) -> None:
    login(client, await make_user(balance=1))

    async def create():
        return await client.post(
            "/api/generations",
            files={"car": image_file()},
            data={"params": json.dumps({"tint": True})},
        )

    responses = await asyncio.gather(*(create() for _ in range(3)))
    codes = sorted(response.status_code for response in responses)
    assert codes == [202, 402, 402]
    assert (await client.get("/api/users/me")).json()["balance"] == 0
