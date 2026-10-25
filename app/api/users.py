from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.schemas.user import UserRead
from app.services.balance import get_balance

router = APIRouter(prefix=settings.prefix.users_prefix, tags=["users"])


@router.get("/me", response_model=UserRead, summary="Текущий пользователь и баланс")
async def read_me(user: CurrentUser, session: SessionDep) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        balance=await get_balance(session, user.id),
        created_at=user.created_at,
    )
