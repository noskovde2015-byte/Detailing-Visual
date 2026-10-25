"""Воркер очереди генераций.

Запуск: poetry run arq app.worker.WorkerSettings
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from arq import Retry, cron, func

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.db_helper import db_helper
from app.services.generation_queue import PROCESS_GENERATION_JOB, redis_settings
from app.services.generation_runner import (
    GenerationOutcome,
    fail_stale_generations,
    run_generation,
)
from app.services.image_generator import get_image_generator
from app.services.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)

queue_config = settings.queue

# Запас сверх нашего таймаута: arq должен снимать задачу только если
# собственный таймаут генерации почему-то не сработал.
ARQ_TIMEOUT_MARGIN_SECONDS = 30

Ctx = dict[str, Any]


async def startup(ctx: Ctx) -> None:
    # setdefault: тесты подставляют свои зависимости через ctx.
    ctx.setdefault("session_factory", db_helper.session_factory)
    ctx.setdefault("generator", get_image_generator())
    ctx.setdefault("storage", get_storage())
    logger.info(
        "Воркер запущен: очередь %s, параллельно до %d генераций, генератор %s",
        queue_config.name,
        queue_config.max_concurrent_generations,
        ctx["generator"].name,
    )


async def shutdown(ctx: Ctx) -> None:
    await db_helper.dispose()


async def process_generation(ctx: Ctx, generation_id: str) -> str:
    job_try: int = ctx["job_try"]
    outcome = await run_generation(
        uuid.UUID(generation_id),
        session_factory=ctx["session_factory"],
        generator=ctx["generator"],
        storage=ctx["storage"],
        timeout_seconds=queue_config.job_timeout_seconds,
        allow_retry=job_try < queue_config.max_tries,
    )
    if outcome is GenerationOutcome.RETRY:
        # Линейная задержка: 1 мин, 2 мин... Сбои Google обычно короткие.
        raise Retry(defer=queue_config.retry_delay_seconds * job_try)
    return outcome.value


async def sweep_stale_generations(ctx: Ctx) -> int:
    return await fail_stale_generations(
        ctx["session_factory"],
        pending_older_than=timedelta(minutes=queue_config.stale_pending_minutes),
        processing_older_than=timedelta(minutes=queue_config.stale_processing_minutes),
    )


class WorkerSettings:
    functions = (
        func(
            process_generation,
            name=PROCESS_GENERATION_JOB,
            # +1: попытка, которую arq делает после отмены при остановке воркера,
            # не должна съедать попытку повтора после сбоя Google.
            max_tries=queue_config.max_tries + 1,
            timeout=queue_config.job_timeout_seconds + ARQ_TIMEOUT_MARGIN_SECONDS,
            keep_result=timedelta(hours=1),
        ),
    )
    cron_jobs = (
        cron(
            sweep_stale_generations,
            minute=set(range(0, 60, queue_config.stale_check_interval_minutes)),
            run_at_startup=True,
            unique=True,
        ),
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    queue_name = queue_config.name
    max_jobs = queue_config.max_concurrent_generations
    # Дать идущим генерациям закончиться при остановке (деплой), а не обрывать их.
    job_completion_wait = queue_config.job_timeout_seconds

    health_check_interval = 30
