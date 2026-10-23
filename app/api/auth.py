import logging
import uuid

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import ClientInfoDep, CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import (
    access_token_lifetime,
    create_access_token,
    refresh_token_lifetime,
)
from app.services.auth_sessions import (
    InvalidRefreshTokenError,
    create_refresh_session,
    revoke_all_user_sessions,
    revoke_refresh_session,
    rotate_refresh_session,
)
from app.services.users import (
    AccountConflictError,
    GoogleProfile,
    get_or_create_google_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.prefix.auth_prefix, tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google.client_id,
    client_secret=settings.google.client_secret.get_secret_value(),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

REFRESH_COOKIE_PATH = f"{settings.prefix.api_prefix}{settings.prefix.auth_prefix}"


def _set_auth_cookies(
    response: Response, user_id: uuid.UUID, refresh_token: str
) -> None:
    common = {
        "httponly": True,
        "secure": settings.auth.cookie_secure,
        "samesite": "lax",
    }
    response.set_cookie(
        settings.auth.access_cookie_name,
        create_access_token(user_id),
        max_age=int(access_token_lifetime().total_seconds()),
        path="/",
        **common,
    )
    response.set_cookie(
        settings.auth.refresh_cookie_name,
        refresh_token,
        max_age=int(refresh_token_lifetime().total_seconds()),
        path=REFRESH_COOKIE_PATH,
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth.access_cookie_name, path="/")
    response.delete_cookie(settings.auth.refresh_cookie_name, path=REFRESH_COOKIE_PATH)


def _frontend_redirect(path: str = "/") -> RedirectResponse:
    return RedirectResponse(f"{settings.auth.frontend_url}{path}", status_code=302)


def _login_error(code: str) -> RedirectResponse:
    return _frontend_redirect(f"/login?error={code}")


@router.get("/google/login")
async def google_login(request: Request) -> RedirectResponse:
    try:
        return await oauth.google.authorize_redirect(
            request, settings.google.redirect_uri
        )
    except httpx.HTTPError:
        logger.exception("Google недоступен на шаге /login")
        return _login_error("unavailable")


@router.get("/google/callback")
async def google_callback(
    request: Request, session: SessionDep, client: ClientInfoDep
) -> RedirectResponse:
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        logger.warning("Ошибка OAuth при входе через Google", exc_info=True)
        return _login_error("oauth")
    except httpx.HTTPError:
        logger.exception("Google недоступен на шаге /callback")
        return _login_error("unavailable")

    userinfo = token.get("userinfo") or {}
    if not userinfo.get("sub") or not userinfo.get("email"):
        return _login_error("profile")
    if not userinfo.get("email_verified"):
        return _login_error("email_not_verified")

    try:
        user = await get_or_create_google_user(
            session,
            GoogleProfile(
                sub=userinfo["sub"],
                email=userinfo["email"],
                name=userinfo.get("name"),
            ),
        )
    except AccountConflictError:
        logger.warning("Конфликт аккаунтов при входе, sub=%s", userinfo["sub"])
        return _login_error("account_conflict")

    refresh_token = await create_refresh_session(session, user.id, client)

    response = _frontend_redirect()
    _set_auth_cookies(response, user.id, refresh_token)
    return response


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    request: Request, session: SessionDep, client: ClientInfoDep
) -> Response:
    token = request.cookies.get(settings.auth.refresh_cookie_name)

    try:
        if not token:
            raise InvalidRefreshTokenError
        issued = await rotate_refresh_session(session, token, client)
    except InvalidRefreshTokenError:
        response = JSONResponse(
            {"detail": "Сессия истекла, войдите заново"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        _clear_auth_cookies(response)
        return response

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_auth_cookies(response, issued.user_id, issued.token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep) -> Response:
    token = request.cookies.get(settings.auth.refresh_cookie_name)
    if token:
        await revoke_refresh_session(session, token)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser, session: SessionDep) -> Response:
    await revoke_all_user_sessions(session, user.id)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response
