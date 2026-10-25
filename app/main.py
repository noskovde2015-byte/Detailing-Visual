import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import admin, auth, generations, health, users
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.db_helper import db_helper
from app.services.generation_queue import ArqGenerationQueue
from app.services.generation_runner import fail_stale_generations
from app.services.storage import get_storage

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    queue: ArqGenerationQueue | None = None
    if settings.queue.backend == "arq":
        # Зависшие задачи убирает воркер по расписанию. Здесь этого делать нельзя:
        # перезапуск API больше не обрывает генерации, они живут в воркере.
        queue = await ArqGenerationQueue.connect()
        app.state.generation_queue = queue
    else:
        logger.warning("Очередь генераций: background (только для разработки)")
        await fail_stale_generations(
            db_helper.session_factory,
            pending_older_than=timedelta(0),
            processing_older_than=timedelta(0),
        )
    try:
        yield
    finally:
        if queue is not None:
            await queue.close()
        await get_storage().close()
        await db_helper.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.auth.secret_key.get_secret_value(),
    same_site="lax",
    https_only=settings.auth.cookie_secure,
    max_age=600,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.auth.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

api_router = APIRouter(prefix=settings.prefix.api_prefix)
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(generations.router)
api_router.include_router(admin.router)
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.run.host,
        port=settings.run.port,
        reload=True,
    )
