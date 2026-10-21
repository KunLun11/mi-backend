"""Общие FastAPI-dependencies: БД, Redis, текущий пользователь."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.database import get_session
from app.models import User, UserRole
from app.services import token_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_access_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    redis: RedisDep,
) -> token_service.AccessTokenPayload:
    """Декодировать access-токен и проверить blacklist."""
    if credentials is None:
        raise _unauthorized("not_authenticated")

    try:
        payload = token_service.decode_access_token(credentials.credentials)
    except token_service.TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    if await token_service.is_access_token_blacklisted(redis, payload.jti):
        raise _unauthorized("token_revoked")

    return payload


async def get_current_user(
    payload: Annotated[token_service.AccessTokenPayload, Depends(get_access_payload)],
    db: SessionDep,
) -> User:
    """Загрузить активного пользователя по `sub` access-токена."""
    user = await db.get(User, payload.sub)
    if user is None or not user.is_active:
        raise _unauthorized("user_inactive")
    return user


AccessPayloadDep = Annotated[token_service.AccessTokenPayload, Depends(get_access_payload)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(role: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency-фабрика: пускать только пользователя с указанной ролью."""

    async def dependency(user: CurrentUser) -> User:
        if user.role is not role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden_role",
            )
        return user

    return dependency


ClientUser = Annotated[User, Depends(require_role(UserRole.CLIENT))]
PsychologistUser = Annotated[User, Depends(require_role(UserRole.PSYCHOLOGIST))]
