"""Полный путь через настоящий Redis: API → очередь arq → воркер → результат.

Запуск: TEST_DATABASE_URL=... TEST_REDIS_URL=redis://localhost:6379/15 pytest
База Redis из TEST_REDIS_URL очищается, не указывайте рабочую.
"""

import os
from collections.abc import AsyncIterator, Sequence

import pytest
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import create_worker
from httpx import AsyncClient

from app.api.generations import get_generation_queue
from app.core.config import settings
from app.db.db_helper import db_helper
from app.main import app
from app.services.fake_generator import FakeImageGenerator
from app.services.generation_queue import ArqGenerationQueue, generation_job_id
from app.services.image_generator import (
    GenerationTemporaryError,
    ImageData,
    ImageGenerator,
)
from app.services.storage import LocalStorage
from app.worker import WorkerSettings
from tests.integration.conftest import image_file, login

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not TEST_REDIS_URL, reason="не задан TEST_REDIS_URL"),
]

URL = "/api/generations"


@pytest.fixture
async def redis() -> AsyncIterator[ArqRedis]:
    assert TEST_REDIS_URL is not None
    pool = await create_pool(RedisSettings.from_dsn(TEST_REDIS_URL))
    await pool.flushdb()
    yield pool
    await pool.flushdb()
    await pool.aclose()


@pytest.fixture
def arq_queue(redis: ArqRedis) -> AsyncIterator[ArqGenerationQueue]:
    queue = ArqGenerationQueue(redis, settings.queue.name)
    app.dependency_overrides[get_generation_queue] = lambda: queue
    yield queue
    app.dependency_overrides.pop(get_generation_queue, None)


async def _run_worker(
    redis: ArqRedis, storage: LocalStorage, generator: ImageGenerator
) -> None:
    worker = create_worker(
        WorkerSettings,
        redis_pool=redis,
        burst=True,
        poll_delay=0,
        handle_signals=False,
        cron_jobs=(),
        on_shutdown=None,
        ctx={
            "session_factory": db_helper.session_factory,
            "storage": storage,
            "generator": generator,
        },
    )
    try:
        await worker.main()
    finally:
        await worker.close()


async def _create(client: AsyncClient) -> dict:
    response = await client.post(
        URL,
        files={"car": image_file()},
        data={"params": '{"antichrome": true}'},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def test_generation_goes_through_worker(
    client: AsyncClient,
    make_user,
    redis: ArqRedis,
    arq_queue: ArqGenerationQueue,
    storage: LocalStorage,
) -> None:
    login(client, await make_user())
    created = await _create(client)

    # API только поставил задачу: без воркера генерация ждёт.
    assert (await client.get(f"{URL}/{created['id']}")).json()["status"] == "pending"
    queued = await redis.zrange(settings.queue.name, 0, -1)
    assert [job.decode() for job in queued] == [generation_job_id(created["id"])]

    await _run_worker(redis, storage, FakeImageGenerator(delay_seconds=0))

    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "done", body
    assert (await client.get(body["result_url"])).status_code == 200


async def test_temporary_failure_is_retried(
    client: AsyncClient,
    make_user,
    redis: ArqRedis,
    arq_queue: ArqGenerationQueue,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings.queue, "retry_delay_seconds", 0)

    class FlakyGenerator(ImageGenerator):
        name = "flaky"
        calls = 0

        async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
            FlakyGenerator.calls += 1
            if FlakyGenerator.calls == 1:
                raise GenerationTemporaryError("Сервис генерации временно перегружен.")
            return images[0]

    login(client, await make_user())
    created = await _create(client)

    await _run_worker(redis, storage, FlakyGenerator())

    body = (await client.get(f"{URL}/{created['id']}")).json()
    assert body["status"] == "done", body
    assert FlakyGenerator.calls == 2


async def test_same_generation_is_not_queued_twice(
    redis: ArqRedis, arq_queue: ArqGenerationQueue
) -> None:
    import uuid

    generation_id = uuid.uuid4()
    await arq_queue.enqueue(generation_id)
    await arq_queue.enqueue(generation_id)
    assert await redis.zcard(settings.queue.name) == 1
