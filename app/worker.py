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
from app.services.cleanup import cleanup_storage
from app.services.generation_pause import GenerationPause, resume_generations
from app.services.generation_queue import (
    PROCESS_GENERATION_JOB,
    ArqGenerationQueue,
    redis_settings,
)
from app.services.generation_runner import (
    INTERRUPTED_ERROR,
    QUEUE_UNAVAILABLE_ERROR,
    GenerationOutcome,
    fail_stale_generations,
    run_generation,
)
from app.services.image_generator import (
    GenerationUnavailableError,
    get_image_generator,
)
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


def _pause(ctx: Ctx) -> GenerationPause:
    if "pause" not in ctx:
        ctx["pause"] = GenerationPause(ctx["redis"], queue_config.name)
    return ctx["pause"]


async def shutdown(ctx: Ctx) -> None:
    await ctx["storage"].close()
    await db_helper.dispose()


async def process_generation(ctx: Ctx, generation_id: str) -> str:
    pause = _pause(ctx)
    if await pause.is_paused():
        # Генерация остаётся pending. Задачу в arq завершаем: при снятии паузы
        # все ждущие генерации поставят в очередь заново (resume_generations).
        logger.info("Генерации на паузе, генерация %s ждёт", generation_id)
        return GenerationOutcome.PAUSED.value

    async def on_outage(exc: GenerationUnavailableError) -> None:
        await pause.pause(exc.reason, exc.detail)

    job_try: int = ctx["job_try"]
    outcome = await run_generation(
        uuid.UUID(generation_id),
        session_factory=ctx["session_factory"],
        generator=ctx["generator"],
        storage=ctx["storage"],
        timeout_seconds=queue_config.job_timeout_seconds,
        allow_retry=job_try < queue_config.max_tries,
        on_outage=on_outage,
    )
    if outcome is GenerationOutcome.RETRY:
        # Линейная задержка: 1 мин, 2 мин... Сбои Google обычно короткие.
        raise Retry(defer=queue_config.retry_delay_seconds * job_try)
    return outcome.value


async def sweep_stale_generations(ctx: Ctx) -> int:
    paused = await _pause(ctx).is_paused()
    return await fail_stale_generations(
        ctx["session_factory"],
        pending_older_than=timedelta(minutes=queue_config.stale_pending_minutes),
        processing_older_than=timedelta(minutes=queue_config.stale_processing_minutes),
        # Пауза затянулась дольше, чем разумно ждать: возвращаем на баланс.
        pending_error=QUEUE_UNAVAILABLE_ERROR if paused else INTERRUPTED_ERROR,
    )


async def watch_generation_pause(ctx: Ctx) -> str:
    """Раз в минуту: если генерации стоят из-за связи, проверить её и
    возобновить самим. Остальные причины снимает администратор."""
    pause = _pause(ctx)
    state = await pause.get()
    if state is None:
        return "running"
    if not state.reason.auto_resume:
        return f"paused:{state.reason}"

    try:
        await ctx["generator"].check()
    except GenerationUnavailableError as exc:
        # Всё ещё недоступно. Если причина уточнилась (связь появилась, а Google
        # ответил «регион не поддерживается»), записываем новую.
        await pause.pause(exc.reason, exc.detail)
        return f"paused:{exc.reason}"
    except Exception:
        logger.exception("Проверка доступности генерации не удалась")
        return f"paused:{state.reason}"

    requeued = await resume_generations(
        pause,
        ctx["session_factory"],
        ArqGenerationQueue(ctx["redis"], queue_config.name),
    )
    logger.warning(
        "Связь восстановлена, генерации возобновлены (%d в очереди)", requeued
    )
    return "resumed"


async def cleanup_storage_files(ctx: Ctx) -> int:
    cleanup = settings.cleanup
    return await cleanup_storage(
        ctx["session_factory"],
        ctx["storage"],
        failed_retention=timedelta(days=cleanup.failed_files_retention_days),
        batch_size=cleanup.batch_size,
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
        # Раз в час, не в 00 минут: в ровный час обычно и так пик задач.
        cron(cleanup_storage_files, minute={17}, unique=True),
        cron(watch_generation_pause, second={30}, unique=True),
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    queue_name = queue_config.name
    max_jobs = queue_config.max_concurrent_generations
    # Дать идущим генерациям закончиться при остановке (деплой), а не обрывать их.
    job_completion_wait = queue_config.job_timeout_seconds
    # Как часто воркер отмечается в Redis. По этой отметке работает
    # `arq --check` (healthcheck в Docker). По умолчанию в arq это раз в час.
    health_check_interval = 30
