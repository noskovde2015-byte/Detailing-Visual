from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import settings
from app.schemas.user import UserRead

router = APIRouter(prefix=settings.prefix.users_prefix, tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
