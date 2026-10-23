from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import auth, generations, health, users
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.db_helper import db_helper
from app.services.generation_runner import fail_stale_generations

STALE_GENERATION_AFTER = timedelta(minutes=15)

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await fail_stale_generations(db_helper.session_factory, STALE_GENERATION_AFTER)
    yield
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
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.run.host,
        port=settings.run.port,
        reload=True,
    )
