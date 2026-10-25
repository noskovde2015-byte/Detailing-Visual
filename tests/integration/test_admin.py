import json
from collections.abc import Sequence

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api import generations as generations_api
from app.core.config import settings
from app.db.db_helper import db_helper
from app.models.refresh_session import RefreshSession
from app.models.user import User
from app.services.auth_sessions import ClientInfo, create_refresh_session
from app.services.image_generator import (
    GenerationRefusedError,
    ImageData,
    ImageGenerator,
)
from tests.integration.conftest import image_file, login

pytestmark = pytest.mark.anyio

ADMIN = "/api/admin"


async def _generate(client: AsyncClient):
    return await client.post(
        "/api/generations",
        files={"car": image_file()},
        data={"params": json.dumps({"antichrome": True})},
    )


async def _grant(client: AsyncClient, user_id, amount: int, reason: str | None = None):
    return await client.post(
        f"{ADMIN}/users/{user_id}/credits",
        json={"amount": amount, "reason": reason},
    )


async def test_regular_user_has_no_access(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    assert (await client.get(f"{ADMIN}/users")).status_code == 403
    assert (await client.get(f"{ADMIN}/stats")).status_code == 403


async def test_anonymous_has_no_access(client: AsyncClient) -> None:
    assert (await client.get(f"{ADMIN}/users")).status_code == 401


async def test_list_and_search_users(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    target = await make_user()
    login(client, admin)

    page = (await client.get(f"{ADMIN}/users")).json()
    assert page["total"] == 2

    found = (
        await client.get(f"{ADMIN}/users", params={"search": target.email[:8]})
    ).json()
    assert [u["id"] for u in found["items"]] == [str(target.id)]

    nothing = (await client.get(f"{ADMIN}/users", params={"search": "%"})).json()
    assert nothing["total"] == 0


async def test_grant_bonus_spent_after_daily_limit(
    client: AsyncClient, make_user
) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()

    login(client, admin)
    response = await _grant(client, user.id, 2, "Компенсация за баг")
    assert response.status_code == 201, response.text
    assert response.json()["granted_by_id"] == str(admin.id)

    login(client, user)
    daily = settings.generation.free_daily_limit
    for _ in range(daily):
        body = (await _generate(client)).json()
        assert body["used_bonus"] is False

    for _ in range(2):
        response = await _generate(client)
        assert response.status_code == 202
        assert response.json()["used_bonus"] is True

    quota = (await client.get("/api/generations/quota")).json()
    assert quota["bonus_remaining"] == 0
    assert quota["remaining"] == 0
    assert (await _generate(client)).status_code == 429

    login(client, admin)
    detail = (await client.get(f"{ADMIN}/users/{user.id}")).json()
    assert detail["user"]["generations_total"] == daily + 2
    assert detail["user"]["bonus_remaining"] == 0


async def test_failed_bonus_generation_is_refunded(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RefusingGenerator(ImageGenerator):
        name = "refusing"

        async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
            raise GenerationRefusedError("Отказ")

    admin = await make_user(is_admin=True)
    user = await make_user()
    login(client, admin)
    await _grant(client, user.id, 1)
    await client.patch(f"{ADMIN}/users/{user.id}", json={"plan": "free"})

    monkeypatch.setattr(settings.generation, "free_daily_limit", 0)
    monkeypatch.setattr(generations_api, "get_image_generator", RefusingGenerator)

    login(client, user)
    body = (await _generate(client)).json()
    assert body["used_bonus"] is True

    quota = (await client.get("/api/generations/quota")).json()
    assert quota["bonus_remaining"] == 1


async def test_cannot_take_more_than_balance(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()
    login(client, admin)

    await _grant(client, user.id, 3)
    assert (await _grant(client, user.id, -2)).status_code == 201
    assert (await _grant(client, user.id, -5)).status_code == 409
    assert (await _grant(client, user.id, 0)).status_code == 422

    history = (await client.get(f"{ADMIN}/users/{user.id}/credits")).json()
    assert [item["amount"] for item in history["items"]] == [-2, 3]


async def test_block_user_revokes_access(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()
    async with db_helper.session_factory() as session:
        await create_refresh_session(session, user.id, ClientInfo(None, None))

    login(client, admin)
    response = await client.patch(f"{ADMIN}/users/{user.id}", json={"is_blocked": True})
    assert response.status_code == 200
    assert response.json()["is_blocked"] is True

    async with db_helper.session_factory() as session:
        active = await session.scalar(
            select(func.count()).where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    assert active == 0

    login(client, user)
    assert (await client.get("/api/users/me")).status_code == 403

    login(client, admin)
    await client.patch(f"{ADMIN}/users/{user.id}", json={"is_blocked": False})
    login(client, user)
    assert (await client.get("/api/users/me")).status_code == 200


async def test_admin_cannot_block_self_or_admins(
    client: AsyncClient, make_user
) -> None:
    admin = await make_user(is_admin=True)
    other_admin = await make_user(is_admin=True)
    login(client, admin)

    for target in (admin, other_admin):
        response = await client.patch(
            f"{ADMIN}/users/{target.id}", json={"is_blocked": True}
        )
        assert response.status_code == 409


async def test_change_plan(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()
    login(client, admin)

    response = await client.patch(f"{ADMIN}/users/{user.id}", json={"plan": "pro"})
    assert response.json()["plan"] == "pro"

    detail = (await client.get(f"{ADMIN}/users/{user.id}")).json()
    assert detail["quota"]["daily_limit"] == settings.generation.pro_daily_limit

    bad = await client.patch(f"{ADMIN}/users/{user.id}", json={"plan": "vip"})
    assert bad.status_code == 422


async def test_admin_sees_any_generation(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()

    login(client, user)
    created = (await _generate(client)).json()

    login(client, admin)
    listed = (await client.get(f"{ADMIN}/users/{user.id}/generations")).json()
    assert listed["total"] == 1

    detail = (await client.get(f"{ADMIN}/generations/{created['id']}")).json()
    assert detail["result_url"].startswith(f"{ADMIN}/generations/")

    image = await client.get(detail["result_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"


async def test_stats(client: AsyncClient, make_user) -> None:
    admin = await make_user(is_admin=True)
    user = await make_user()
    login(client, user)
    await _generate(client)

    login(client, admin)
    stats = (await client.get(f"{ADMIN}/stats")).json()
    assert stats["users_total"] == 2
    assert stats["generations_24h"] == 1
    assert stats["generations_24h_by_status"]["done"] == 1


async def test_unknown_user_is_404(client: AsyncClient, make_user) -> None:
    login(client, await make_user(is_admin=True))
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"{ADMIN}/users/{missing}")).status_code == 404
    assert (await _grant(client, missing, 1)).status_code == 404


async def test_blocked_user_cannot_refresh(client: AsyncClient, make_user) -> None:
    user = await make_user()
    async with db_helper.session_factory() as session:
        token = await create_refresh_session(session, user.id, ClientInfo(None, None))

    async with db_helper.session_factory() as session:
        db_user = await session.get(User, user.id)
        db_user.is_blocked = True
        await session.commit()

    client.cookies.clear()
    client.cookies.set(settings.auth.refresh_cookie_name, token, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401
