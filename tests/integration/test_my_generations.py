import io
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, update

from app.api import generations as generations_api
from app.api.generations import get_generation_queue
from app.db.db_helper import db_helper
from app.main import app
from app.models.generation import Generation
from app.models.generation_image import GenerationImage
from app.services import generation_runner
from app.services.cleanup import cleanup_storage
from app.services.generation_queue import GenerationQueue
from app.services.image_generator import (
    GenerationRefusedError,
    ImageData,
    ImageGenerator,
)
from app.services.storage import LocalStorage
from tests.integration.conftest import image_file, login

pytestmark = pytest.mark.anyio

URL = "/api/generations"


async def _create(client: AsyncClient, **files) -> dict:
    upload = {"car": image_file(size=(1200, 900))}
    upload.update(files)
    response = await client.post(
        URL, files=upload, data={"params": json.dumps({"antichrome": True})}
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _stored_keys(generation_id: str) -> list[str]:
    async with db_helper.session_factory() as session:
        return list(
            await session.scalars(
                select(GenerationImage.storage_key).where(
                    GenerationImage.generation_id == uuid.UUID(generation_id)
                )
            )
        )


class RefusingGenerator(ImageGenerator):
    name = "refusing"

    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        raise GenerationRefusedError("Модель не смогла обработать это фото.")


class IdleQueue(GenerationQueue):
    """Принимает задачу, но не выполняет: генерация остаётся pending."""

    async def enqueue(
        self, generation_id: uuid.UUID, *, tag: str | None = None
    ) -> None:
        return None


# ---------- превью ----------


async def test_done_generation_has_small_jpeg_preview(
    client: AsyncClient, make_user
) -> None:
    login(client, await make_user())
    created = await _create(client)

    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "done"
    assert body["preview_url"].endswith("/images/preview")
    assert body["input_roles"] == ["car"]

    preview = await client.get(body["preview_url"])
    assert preview.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(preview.content)) as image:
        assert max(image.size) == 512


async def test_preview_failure_does_not_fail_generation(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_preview(data: bytes) -> None:
        raise OSError("broken")

    monkeypatch.setattr(generation_runner, "make_preview", broken_preview)
    login(client, await make_user())
    created = await _create(client)

    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "done"
    assert body["result_url"]
    assert body["preview_url"] is None


# ---------- фильтр ----------


async def test_filter_by_status(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, await make_user())
    done = await _create(client)
    monkeypatch.setattr(generations_api, "get_image_generator", RefusingGenerator)
    failed = await _create(client)

    only_done = (await client.get(URL, params={"status": "done"})).json()
    assert [item["id"] for item in only_done["items"]] == [done["id"]]
    assert only_done["total"] == 1

    only_failed = (await client.get(URL, params={"status": "failed"})).json()
    assert [item["id"] for item in only_failed["items"]] == [failed["id"]]

    assert (await client.get(URL, params={"status": "nope"})).status_code == 422


# ---------- удаление ----------


async def test_delete_generation(
    client: AsyncClient, make_user, storage: LocalStorage
) -> None:
    login(client, await make_user())
    created = await _create(client)
    keys = await _stored_keys(created["id"])
    assert len(keys) == 3  # car, result, preview

    response = await client.delete(f"{URL}/{created['id']}")
    assert response.status_code == 204

    assert (await client.get(f"{URL}/{created['id']}")).status_code == 404
    assert (await client.get(f"{URL}/{created['id']}/images/car")).status_code == 404
    assert (await client.get(URL)).json()["total"] == 0
    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 404

    # Фото удалены из хранилища и из базы.
    assert await _stored_keys(created["id"]) == []
    for key in keys:
        assert not (storage._root / key).exists()


async def test_delete_does_not_refund_balance(client: AsyncClient, make_user) -> None:
    login(client, await make_user(balance=3))
    created = await _create(client)

    await client.delete(f"{URL}/{created['id']}")

    assert (await client.get("/api/users/me")).json()["balance"] == 2


async def test_cannot_delete_running_generation(client: AsyncClient, make_user) -> None:
    app.dependency_overrides[get_generation_queue] = IdleQueue
    try:
        login(client, await make_user())
        created = await _create(client)
        assert (await client.get(f"{URL}/{created['id']}")).json()[
            "status"
        ] == "pending"

        response = await client.delete(f"{URL}/{created['id']}")
    finally:
        app.dependency_overrides.pop(get_generation_queue, None)

    assert response.status_code == 409


async def test_cannot_delete_other_users_generation(
    client: AsyncClient, make_user
) -> None:
    login(client, await make_user())
    created = await _create(client)

    login(client, await make_user())
    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 404


async def test_admin_still_sees_deleted_generation(
    client: AsyncClient, make_user
) -> None:
    user = await make_user()
    login(client, user)
    created = await _create(client)
    await client.delete(f"{URL}/{created['id']}")

    login(client, await make_user(is_admin=True))
    page = (await client.get(f"/api/admin/users/{user.id}/generations")).json()
    assert [item["id"] for item in page["items"]] == [created["id"]]
    assert page["items"][0]["deleted_at"] is not None
    assert page["items"][0]["result_url"] is None


async def test_storage_failure_on_delete_is_cleaned_up_later(
    client: AsyncClient,
    make_user,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login(client, await make_user())
    created = await _create(client)

    async def broken_delete(key: str) -> None:
        raise OSError("storage is down")

    monkeypatch.setattr(storage, "delete", broken_delete)
    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204
    assert len(await _stored_keys(created["id"])) == 3

    monkeypatch.undo()
    purged = await cleanup_storage(
        db_helper.session_factory,
        storage,
        failed_retention=timedelta(days=7),
        batch_size=100,
    )
    assert purged == 1
    assert await _stored_keys(created["id"]) == []


# ---------- уборщик ----------


async def test_cleanup_purges_only_old_failed_generations(
    client: AsyncClient,
    make_user,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login(client, await make_user())
    done = await _create(client)
    monkeypatch.setattr(generations_api, "get_image_generator", RefusingGenerator)
    old_failed = await _create(client)
    recent_failed = await _create(client)

    async with db_helper.session_factory() as session:
        await session.execute(
            update(Generation)
            .where(Generation.id == uuid.UUID(old_failed["id"]))
            .values(finished_at=datetime.now(UTC) - timedelta(days=8))
        )
        await session.commit()

    purged = await cleanup_storage(
        db_helper.session_factory,
        storage,
        failed_retention=timedelta(days=7),
        batch_size=100,
    )

    assert purged == 1
    assert await _stored_keys(old_failed["id"]) == []
    assert len(await _stored_keys(recent_failed["id"])) == 1
    assert len(await _stored_keys(done["id"])) == 3

    # Сама запись остаётся: она нужна для истории и лимитов.
    body = (await client.get(f"{URL}/{old_failed['id']}")).json()
    assert body["status"] == "failed"
    assert body["input_roles"] == []

    # Повторный запуск ничего не делает.
    assert (
        await cleanup_storage(
            db_helper.session_factory,
            storage,
            failed_retention=timedelta(days=7),
            batch_size=100,
        )
        == 0
    )
