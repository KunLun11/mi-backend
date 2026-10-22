"""Выпуск, ротация и отзыв токенов; blacklist access-токенов в Redis."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from jose import JWTError, jwt
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import generate_refresh_token, sha256_hex
from app.models import User, UserRole, UserSession
from app.schemas.auth import TokenResponse

settings = get_settings()

_REFRESH_USED_PREFIX = "refresh:used:"
_BLACKLIST_PREFIX = "blacklist:"


class TokenError(Exception):
    """Токен невалиден, просрочен или отозван."""


class AccessTokenPayload(BaseModel):
    """Проверенные claims access-токена."""

    sub: UUID
    role: UserRole
    jti: UUID
    iat: int
    exp: int
    iss: str
    type: Literal["access"]


def utcnow() -> datetime:
    """Текущее время UTC (aware)."""
    return datetime.now(UTC)


def _truncate(value: str | None, limit: int) -> str | None:
    """Обрезать строку до длины колонки."""
    return value[:limit] if value else None


def create_access_token(user: User) -> str:
    """Создать подписанный JWT access-токен."""
    now = utcnow()
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role.value,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.jwt_issuer,
        "type": "access",
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return cast(str, token)


def decode_access_token(token: str) -> AccessTokenPayload:
    """Декодировать и провалидировать access-токен."""
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            # `exp` проверяем вручную ниже, чтобы отдать отдельный код
            # `token_expired` (фронт по нему запускает refresh).
            options={"verify_exp": False},
        )
    except JWTError as exc:
        raise TokenError("invalid_token") from exc

    try:
        payload = AccessTokenPayload.model_validate(raw)
    except ValidationError as exc:
        raise TokenError("invalid_token") from exc

    if payload.exp <= int(utcnow().timestamp()):
        raise TokenError("token_expired")
    return payload


def build_token_response(user: User, refresh_token: str) -> TokenResponse:
    """Собрать ответ с новой парой токенов."""
    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


async def create_session(
    db: AsyncSession,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
) -> TokenResponse:
    """Создать refresh-сессию и вернуть пару токенов (без commit)."""
    now = utcnow()
    refresh_token = generate_refresh_token()

    db.add(
        UserSession(
            user_id=user.id,
            family_id=uuid4(),
            refresh_token_hash=sha256_hex(refresh_token),
            rotation_counter=0,
            user_agent=_truncate(user_agent, 512),
            ip_address=ip_address,
            last_used_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return build_token_response(user, refresh_token)


async def rotate_refresh_token(
    db: AsyncSession,
    redis: Redis,
    raw_refresh_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> TokenResponse:
    """Ротировать refresh-токен с проверкой absolute/idle TTL и reuse."""
    token_hash = sha256_hex(raw_refresh_token)
    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update()
    )
    session = result.scalar_one_or_none()
    now = utcnow()

    if session is None:
        await _handle_reuse(db, redis, token_hash, now)
        raise TokenError("invalid_refresh_token")

    if session.revoked_at is not None:
        raise TokenError("invalid_refresh_token")

    if now > session.expires_at:
        session.revoked_at = now
        await db.commit()
        raise TokenError("invalid_refresh_token")

    if now - session.last_used_at > timedelta(days=settings.session_idle_timeout_days):
        session.revoked_at = now
        await db.commit()
        raise TokenError("invalid_refresh_token")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        session.revoked_at = now
        await db.commit()
        raise TokenError("invalid_refresh_token")

    # Маркер использованного токена: повторное предъявление отзовёт всё семейство.
    ttl_seconds = int((session.expires_at - now).total_seconds())
    if ttl_seconds > 0:
        await redis.set(
            f"{_REFRESH_USED_PREFIX}{token_hash}",
            str(session.family_id),
            ex=ttl_seconds,
        )

    new_refresh_token = generate_refresh_token()
    session.refresh_token_hash = sha256_hex(new_refresh_token)
    session.rotation_counter += 1
    session.last_used_at = now
    if user_agent:
        session.user_agent = user_agent[:512]
    if ip_address:
        session.ip_address = ip_address

    await db.commit()
    return build_token_response(user, new_refresh_token)


async def _handle_reuse(
    db: AsyncSession,
    redis: Redis,
    token_hash: str,
    now: datetime,
) -> None:
    """Если предъявлен уже ротированный токен — отозвать всё семейство."""
    family_id_raw = cast(str | None, await redis.get(f"{_REFRESH_USED_PREFIX}{token_hash}"))
    if not family_id_raw:
        return

    try:
        family_id = UUID(family_id_raw)
    except ValueError:
        return

    await db.execute(
        update(UserSession)
        .where(
            UserSession.family_id == family_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()


async def revoke_session_by_refresh_token(
    db: AsyncSession,
    raw_refresh_token: str,
) -> UserSession | None:
    """Отозвать сессию по refresh-токену (идемпотентно, без commit)."""
    token_hash = sha256_hex(raw_refresh_token)
    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
    return session


async def revoke_all_sessions(db: AsyncSession, user_id: UUID) -> None:
    """Отозвать все активные сессии пользователя (без commit)."""
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )


async def blacklist_access_token(redis: Redis, payload: AccessTokenPayload) -> None:
    """Поместить `jti` в Redis-blacklist до истечения access-токена."""
    ttl_seconds = payload.exp - int(utcnow().timestamp())
    if ttl_seconds > 0:
        await redis.set(f"{_BLACKLIST_PREFIX}{payload.jti}", "1", ex=ttl_seconds)


async def is_access_token_blacklisted(redis: Redis, jti: UUID) -> bool:
    """Проверить, отозван ли access-токен."""
    return bool(await redis.exists(f"{_BLACKLIST_PREFIX}{jti}"))
