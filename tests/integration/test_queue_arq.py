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
from app.services.generation_pause import GenerationPause
from app.services.generation_queue import ArqGenerationQueue, generation_job_id
from app.services.image_generator import (
    GenerationTemporaryError,
    GenerationUnavailableError,
    ImageData,
    ImageGenerator,
    OutageReason,
)
from app.services.storage import LocalStorage
from app.worker import WorkerSettings
from tests.integration.conftest import image_file, login

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")
if not TEST_REDIS_URL and os.environ.get("CI"):
    raise RuntimeError("В CI обязателен TEST_REDIS_URL")

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
    redis: ArqRedis,
    storage: LocalStorage,
    generator: ImageGenerator,
    max_jobs: int | None = None,
) -> None:
    overrides = {} if max_jobs is None else {"max_jobs": max_jobs}
    worker = create_worker(
        WorkerSettings,
        **overrides,
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

        async def generate(
            self,
            prompt: str,
            images: Sequence[ImageData],
            *,
            aspect_ratio: str | None = None,
        ) -> ImageData:
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


# ---------- пауза при сбое «для всех» ----------

ADMIN_STATUS = "/api/admin/generation-status"


class BillingOutage(ImageGenerator):
    """Google: «кончилась предоплата». Считает вызовы, чтобы проверить,
    что заведомо отклоняемые запросы не повторяются."""

    name = "billing-outage"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        self.calls += 1
        raise GenerationUnavailableError(
            "Сервис генерации временно недоступен.",
            reason=OutageReason.BILLING,
            detail="HTTP 402: Prepayment credits are depleted",
        )


class NetworkDown(FakeImageGenerator):
    def __init__(self) -> None:
        super().__init__(delay_seconds=0)
        self.down = True

    async def check(self) -> None:
        if self.down:
            raise GenerationUnavailableError(
                "x", reason=OutageReason.NETWORK, detail="ConnectError"
            )


async def test_outage_pauses_queue_and_admin_resumes(
    client: AsyncClient,
    make_user,
    redis: ArqRedis,
    arq_queue: ArqGenerationQueue,
    storage: LocalStorage,
) -> None:
    user = await make_user(balance=5)
    admin = await make_user(is_admin=True)
    login(client, user)
    first = await _create(client)
    second = await _create(client)

    outage = BillingOutage()
    # По одной задаче за раз, чтобы порядок был определён. В проде задачи,
    # уже начатые параллельно (до max_jobs), успеют сходить в Google.
    await _run_worker(redis, storage, outage, max_jobs=1)

    # Первая упала с «нет оплаты» и поставила паузу, вторая даже не пошла в Google.
    assert outage.calls == 1
    for created in (first, second):
        body = (await client.get(f"{URL}/{created['id']}")).json()
        assert body["status"] == "pending", body

    # Новые генерации не принимаются, баланс не занимается.
    balance_before = (await client.get("/api/users/me")).json()["balance"]
    refused = await client.post(URL, files={"car": image_file()})
    assert refused.status_code == 503
    assert (await client.get("/api/users/me")).json()["balance"] == balance_before
    assert (await client.get(f"{URL}/availability")).json()["available"] is False

    login(client, admin)
    status_body = (await client.get(ADMIN_STATUS)).json()
    assert status_body["paused"] is True
    assert status_body["reason"] == "billing"
    assert status_body["auto_resume"] is False
    assert "402" in status_body["detail"]
    assert status_body["hint"]
    assert status_body["pending_count"] == 2

    resumed = await client.post(f"{ADMIN_STATUS}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["requeued"] == 2
    assert resumed.json()["status"]["paused"] is False

    await _run_worker(redis, storage, FakeImageGenerator(delay_seconds=0))

    login(client, user)
    for created in (first, second):
        body = (await client.get(f"{URL}/{created['id']}")).json()
        assert body["status"] == "done", body
    assert (await client.get(f"{URL}/availability")).json()["available"] is True


async def test_network_outage_resumes_by_itself(
    client: AsyncClient,
    make_user,
    redis: ArqRedis,
    arq_queue: ArqGenerationQueue,
    storage: LocalStorage,
) -> None:
    from app.worker import watch_generation_pause

    login(client, await make_user())
    created = await _create(client)
    pause = GenerationPause(redis, settings.queue.name)
    await pause.pause(OutageReason.NETWORK, "ConnectError")

    generator = NetworkDown()
    await _run_worker(redis, storage, generator)
    assert (await client.get(f"{URL}/{created['id']}")).json()["status"] == "pending"

    ctx = {
        "redis": redis,
        "generator": generator,
        "session_factory": db_helper.session_factory,
    }
    # Связи всё ещё нет — пауза остаётся.
    assert await watch_generation_pause(ctx) == "paused:network"
    assert await pause.is_paused()

    generator.down = False
    assert await watch_generation_pause(ctx) == "resumed"
    assert not await pause.is_paused()

    await _run_worker(redis, storage, generator)
    assert (await client.get(f"{URL}/{created['id']}")).json()["status"] == "done"


async def test_billing_pause_is_not_lifted_automatically(
    redis: ArqRedis, arq_queue: ArqGenerationQueue
) -> None:
    from app.worker import watch_generation_pause

    pause = GenerationPause(redis, settings.queue.name)
    await pause.pause(OutageReason.BILLING, "HTTP 402")
    generator = NetworkDown()
    generator.down = False
    ctx = {"redis": redis, "generator": generator}

    assert await watch_generation_pause(ctx) == "paused:billing"
    assert await pause.is_paused()


async def test_pause_keeps_first_failure_time(redis: ArqRedis) -> None:
    pause = GenerationPause(redis, settings.queue.name)
    first = await pause.pause(OutageReason.NETWORK, "a")
    second = await pause.pause(OutageReason.REGION, "b")
    assert second.since == first.since
    assert second.reason is OutageReason.REGION
    assert (await pause.get()) == second


async def test_admin_manual_pause(
    client: AsyncClient, make_user, arq_queue: ArqGenerationQueue
) -> None:
    admin = await make_user(is_admin=True)
    login(client, admin)

    assert (await client.post(f"{ADMIN_STATUS}/resume")).status_code == 409

    paused = await client.post(f"{ADMIN_STATUS}/pause", json={"comment": "обновляю"})
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["paused"] is True
    assert body["reason"] == "manual"
    assert body["paused_by"] == admin.email
    assert body["detail"] == "обновляю"

    refused = await client.post(URL, files={"car": image_file()})
    assert refused.status_code == 503

    assert (await client.post(f"{ADMIN_STATUS}/resume")).status_code == 200
    assert (await client.get(ADMIN_STATUS)).json()["paused"] is False


async def test_regular_user_cannot_control_queue(
    client: AsyncClient, make_user, arq_queue: ArqGenerationQueue
) -> None:
    login(client, await make_user())
    assert (await client.get(ADMIN_STATUS)).status_code == 403
    assert (await client.post(f"{ADMIN_STATUS}/pause", json={})).status_code == 403
