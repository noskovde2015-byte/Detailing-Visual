import json
import uuid
from collections.abc import Sequence

import pytest
from httpx import AsyncClient

from app.api import generations as generations_api
from app.core.config import settings
from app.main import app
from app.services.colors import render_swatch
from app.services.generation_queue import GenerationQueue, QueueUnavailableError
from app.services.image_generator import (
    GenerationRefusedError,
    ImageData,
    ImageGenerator,
)
from tests.integration.conftest import image_file, login

pytestmark = pytest.mark.anyio

URL = "/api/generations"


async def _create(client: AsyncClient, params: dict | None = None, **files):
    upload = {"car": image_file()}
    upload.update(files)
    return await client.post(
        URL,
        files=upload,
        data={
            "params": json.dumps(params if params is not None else {"antichrome": True})
        },
    )


async def test_requires_auth(client: AsyncClient) -> None:
    response = await _create(client)
    assert response.status_code == 401


async def test_full_flow_with_fake_generator(client: AsyncClient, make_user) -> None:
    login(client, await make_user())

    response = await _create(
        client,
        {"film_finish": "glossy", "antichrome": True},
        film=image_file("film.jpg"),
    )
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["status"] == "pending"
    assert created["input_roles"] == ["car", "film"]
    assert response.headers["location"].endswith(created["id"])

    status_response = await client.get(f"{URL}/{created['id']}")
    body = status_response.json()
    assert body["status"] == "done", body
    assert body["result_url"]

    image = await client.get(body["result_url"], params={"download": True})
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["content-disposition"].startswith("attachment")
    assert image.content.startswith(b"\x89PNG")

    original = await client.get(f"{URL}/{created['id']}/images/car")
    assert original.headers["content-type"] == "image/jpeg"


async def test_no_changes_rejected(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(client, {})
    assert response.status_code == 422


async def test_unknown_param_rejected(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(client, {"antichrome": True, "spoiler": True})
    assert response.status_code == 422


async def test_wheels_require_photo(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(client, {"wheels": {"current_size": 18, "new_size": 20}})
    assert response.status_code == 422


async def test_not_an_image_rejected(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(
        client, car=("car.jpg", b"definitely not jpeg", "image/jpeg")
    )
    assert response.status_code == 422
    assert "car" in response.json()["detail"]


async def test_too_large_upload_rejected(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.generation, "max_upload_bytes", 1000)
    login(client, await make_user())
    response = await _create(client)
    assert response.status_code == 413


async def test_daily_limit(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    limit = settings.generation.free_daily_limit

    for _ in range(limit):
        assert (await _create(client)).status_code == 202

    response = await _create(client)
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["quota"]["remaining"] == 0
    assert "retry-after" in response.headers

    quota = (await client.get(f"{URL}/quota")).json()
    assert quota["daily_limit"] == limit
    assert quota["daily_used"] == limit
    assert quota["remaining"] == 0
    assert quota["resets_at"] is not None


async def test_failed_generation_not_counted(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RefusingGenerator(ImageGenerator):
        name = "refusing"

        async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
            raise GenerationRefusedError("Модель не смогла обработать это фото.")

    monkeypatch.setattr(generations_api, "get_image_generator", RefusingGenerator)
    login(client, await make_user())

    created = (await _create(client)).json()
    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "failed"
    assert body["error"] == "Модель не смогла обработать это фото."
    assert body["result_url"] is None

    quota = (await client.get(f"{URL}/quota")).json()
    assert quota["daily_used"] == 0


async def test_other_user_cannot_see_generation(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    created = (await _create(client)).json()

    login(client, await make_user())
    assert (await client.get(f"{URL}/{created['id']}")).status_code == 404
    assert (await client.get(f"{URL}/{created['id']}/images/result")).status_code == 404


async def test_history_is_paginated(client: AsyncClient, make_user) -> None:
    login(client, await make_user(plan="pro"))
    for _ in range(3):
        await _create(client)

    page = (await client.get(URL, params={"limit": 2})).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2


async def test_palette_color_flow(
    client: AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class CapturingGenerator(ImageGenerator):
        name = "capturing"

        async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
            captured["prompt"] = prompt
            captured["images"] = list(images)
            return images[0]

    monkeypatch.setattr(generations_api, "get_image_generator", CapturingGenerator)
    login(client, await make_user())

    response = await _create(client, {"film_color": "#1f0101", "film_finish": "matte"})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["params"]["film_color"] == "#1F0101"
    assert created["input_roles"] == ["car"]

    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "done", body

    images = captured["images"]
    assert len(images) == 2
    assert images[1] == ImageData(data=render_swatch("#1F0101"), mime_type="image/png")
    assert "very dark red" in captured["prompt"]
    assert "MATTE" in captured["prompt"]

    swatch = await client.get(f"{URL}/{created['id']}/images/film")
    assert swatch.status_code == 404


async def test_film_photo_and_color_rejected(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(
        client, {"film_color": "#1F0101"}, film=image_file("film.jpg")
    )
    assert response.status_code == 422
    assert "что-то одно" in response.json()["detail"]


async def test_invalid_color_rejected(client: AsyncClient, make_user) -> None:
    login(client, await make_user())
    response = await _create(client, {"film_color": "red"})
    assert response.status_code == 422


async def test_queue_unavailable_returns_503_and_refunds(
    client: AsyncClient, make_user
) -> None:
    class BrokenQueue(GenerationQueue):
        async def enqueue(self, generation_id: uuid.UUID) -> None:
            raise QueueUnavailableError("redis is down")

    app.dependency_overrides[generations_api.get_generation_queue] = BrokenQueue
    try:
        login(client, await make_user())
        response = await _create(client)
    finally:
        app.dependency_overrides.pop(generations_api.get_generation_queue, None)

    assert response.status_code == 503
    history = (await client.get(URL)).json()
    assert history["items"][0]["status"] == "failed"
    assert (await client.get(f"{URL}/quota")).json()["daily_used"] == 0
