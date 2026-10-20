from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_helper import db_helper

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    session: AsyncSession = Depends(db_helper.session_getter),
) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
