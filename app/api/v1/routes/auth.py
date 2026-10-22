"""Эндпоинты аутентификации: email + пароль, токены и сессии."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import AccessPayloadDep, CurrentUser, RedisDep, SessionDep
from app.config import get_settings
from app.core.rate_limit import RateLimit
from app.models import OAuthProvider
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OAuthAuthorizeResponse,
    RefreshRequest,
    RegisterRequest,
    ResendCodeRequest,
    SetRoleRequest,
    TokenResponse,
    UserPublic,
    VerifyEmailRequest,
)
from app.services import auth_service, oauth_service, token_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """Вернуть (user_agent, ip) для записи в refresh-сессию."""
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client is not None else None
    return user_agent, ip_address


@router.post(
    "/register",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RateLimit("register", 5, 3600))],
)
async def register(payload: RegisterRequest, db: SessionDep) -> Response:
    """Зарегистрировать пользователя и отправить код на email."""
    await auth_service.register(
        db,
        email=str(payload.email),
        password=payload.password,
        role=payload.role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/verify-email",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit("verify-email", 5, 900, source="email"))],
)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: SessionDep,
) -> TokenResponse:
    """Подтвердить email кодом и получить токены."""
    user_agent, ip_address = _client_meta(request)
    return await auth_service.verify_email(
        db,
        email=str(payload.email),
        code=payload.code,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.post(
    "/resend-code",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RateLimit("resend-code", 1, 60, source="email"))],
)
async def resend_code(payload: ResendCodeRequest, db: SessionDep) -> Response:
    """Отправить новый код подтверждения."""
    await auth_service.resend_code(db, email=str(payload.email))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimit("login", 10, 900))],
)
async def login(
    payload: LoginRequest,
    request: Request,
    db: SessionDep,
) -> TokenResponse:
    """Войти по email и паролю."""
    user_agent, ip_address = _client_meta(request)
    return await auth_service.login(
        db,
        email=str(payload.email),
        password=payload.password,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    db: SessionDep,
    redis: RedisDep,
) -> TokenResponse:
    """Ротировать refresh-токен."""
    user_agent, ip_address = _client_meta(request)
    try:
        return await token_service.rotate_refresh_token(
            db,
            redis,
            payload.refresh_token,
            user_agent,
            ip_address,
        )
    except token_service.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    db: SessionDep,
    redis: RedisDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Отозвать refresh-сессию и (при наличии) текущий access-токен."""
    await auth_service.logout(db, refresh_token=payload.refresh_token)

    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                access_payload = token_service.decode_access_token(token)
            except token_service.TokenError:
                pass
            else:
                await token_service.blacklist_access_token(redis, access_payload)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    user: CurrentUser,
    access_payload: AccessPayloadDep,
    db: SessionDep,
    redis: RedisDep,
) -> Response:
    """Отозвать все сессии пользователя и текущий access-токен."""
    await auth_service.logout_all(db, user_id=user.id)
    await token_service.blacklist_access_token(redis, access_payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/oauth/{provider}/authorize", response_model=OAuthAuthorizeResponse)
async def oauth_authorize(
    provider: OAuthProvider,
    redis: RedisDep,
) -> OAuthAuthorizeResponse:
    """Вернуть URL авторизации провайдера (state хранится в Redis)."""
    authorize_url = await oauth_service.create_authorize_url(redis, provider)
    return OAuthAuthorizeResponse(authorize_url=authorize_url)


@router.get(
    "/oauth/{provider}/callback",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def oauth_callback(
    provider: OAuthProvider,
    request: Request,
    db: SessionDep,
    redis: RedisDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Обработать возврат от провайдера и вернуть пользователя во фронтенд."""
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth_denied",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_oauth_request",
        )

    user_agent, ip_address = _client_meta(request)
    tokens = await oauth_service.complete_callback(
        db,
        redis,
        provider,
        code=code,
        state=state,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    query = urlencode({"access": tokens.access_token, "refresh": tokens.refresh_token})
    return RedirectResponse(
        url=f"{settings.frontend_url.rstrip('/')}/auth/callback?{query}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/set-role", response_model=UserPublic)
async def set_role(
    payload: SetRoleRequest,
    user: CurrentUser,
    db: SessionDep,
) -> UserPublic:
    """Выбрать роль после OAuth-регистрации (однократно)."""
    updated = await oauth_service.set_role(db, user, payload.role)
    return UserPublic.model_validate(updated)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: SessionDep) -> MeResponse:
    """Вернуть текущего пользователя с профилем."""
    return await auth_service.get_me(db, user)
