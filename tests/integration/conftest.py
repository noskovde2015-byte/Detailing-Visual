import io
import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip(
        "Интеграционные тесты пропущены: не задан TEST_DATABASE_URL",
        allow_module_level=True,
    )

from app.api import generations as generations_api
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.db_helper import db_helper
from app.main import app
from app.models.user import User
from app.services.storage import LocalStorage


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db() -> AsyncIterator[None]:
    async with db_helper.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with db_helper.engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    await db_helper.dispose()


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    local = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(generations_api, "get_storage", lambda: local)
    return local


@pytest.fixture
async def make_user(db: None) -> Callable[..., object]:
    async def _make(plan: str = "free", is_admin: bool = False) -> User:
        async with db_helper.session_factory() as session:
            user = User(
                google_sub=uuid.uuid4().hex,
                email=f"{uuid.uuid4().hex}@example.com",
                name="Test",
                plan=plan,
                is_admin=is_admin,
            )
            session.add(user)
            await session.commit()
            return user

    return _make


@pytest.fixture
async def client(db: None, storage: LocalStorage) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def login(client: AsyncClient, user: User) -> None:
    client.cookies.set(settings.auth.access_cookie_name, create_access_token(user.id))


def image_file(name: str = "car.jpg", size: tuple[int, int] = (320, 240)) -> tuple:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(40, 90, 160)).save(buffer, format="JPEG")
    return (name, buffer.getvalue(), "image/jpeg")
