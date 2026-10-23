from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import InvalidTokenError, decode_access_token
from app.db.db_helper import db_helper
from app.models.user import User
from app.services.auth_sessions import ClientInfo
from app.services.users import get_user_by_id

SessionDep = Annotated[AsyncSession, Depends(db_helper.session_getter)]


async def get_current_user(request: Request, session: SessionDep) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
    )

    token = request.cookies.get(settings.auth.access_cookie_name)
    if not token:
        raise unauthorized

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise unauthorized from None

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise unauthorized
    return user


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


CurrentUser = Annotated[User, Depends(get_current_user)]
ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]
