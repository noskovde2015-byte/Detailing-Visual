import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import BackgroundTasks

from app.core.config import settings

logger = logging.getLogger(__name__)

PROCESS_GENERATION_JOB = "process_generation"


class QueueUnavailableError(Exception):
    """Не удалось поставить задачу в очередь (например, Redis недоступен)."""


def generation_job_id(generation_id: uuid.UUID, tag: str | None = None) -> str:
    """id задачи в arq. Одинаковый для одной генерации, поэтому повторная
    постановка той же генерации в очередь не создаст дубль.

    tag — для намеренной повторной постановки (после паузы): arq хранит
    результат прошлой задачи час и не даст поставить задачу с тем же id.
    """
    base = f"generation:{generation_id}"
    return f"{base}:{tag}" if tag else base


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(settings.redis.url))


class GenerationQueue(ABC):
    @abstractmethod
    async def enqueue(
        self, generation_id: uuid.UUID, *, tag: str | None = None
    ) -> None:
        """Ставит генерацию в очередь. При неудаче бросает QueueUnavailableError."""


class ArqGenerationQueue(GenerationQueue):
    def __init__(self, redis: ArqRedis, queue_name: str) -> None:
        self._redis = redis
        self._queue_name = queue_name

    @classmethod
    async def connect(cls) -> "ArqGenerationQueue":
        redis = await create_pool(
            redis_settings(), default_queue_name=settings.queue.name
        )
        return cls(redis, settings.queue.name)

    @property
    def redis(self) -> ArqRedis:
        return self._redis

    async def enqueue(
        self, generation_id: uuid.UUID, *, tag: str | None = None
    ) -> None:
        try:
            job = await self._redis.enqueue_job(
                PROCESS_GENERATION_JOB,
                str(generation_id),
                _job_id=generation_job_id(generation_id, tag),
                _queue_name=self._queue_name,
            )
        except Exception as exc:
            raise QueueUnavailableError(str(exc)) from exc
        if job is None:
            logger.info("Генерация %s уже стоит в очереди", generation_id)

    async def close(self) -> None:
        await self._redis.aclose()


class BackgroundGenerationQueue(GenerationQueue):
    """Выполняет генерацию внутри процесса API после ответа клиенту.

    Только для разработки и тестов: при перезапуске API задачи теряются
    (их потом подберёт fail_stale_generations), а нагрузку нельзя ограничить.
    """

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        execute: Callable[[uuid.UUID], Awaitable[object]],
    ) -> None:
        self._background_tasks = background_tasks
        self._execute = execute

    async def enqueue(
        self, generation_id: uuid.UUID, *, tag: str | None = None
    ) -> None:
        self._background_tasks.add_task(self._execute, generation_id)
