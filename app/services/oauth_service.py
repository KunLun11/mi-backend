"""OAuth 2.0 через authlib: Яндекс, Google и GitHub.

Состояние (`state`) хранится в Redis и погашается при первом callback.
Токены провайдера в JWT не попадают — в `OAuthAccount` они не сохраняются
(на MVP это `None`).
"""

import logging
import secrets
from dataclasses import dataclass
from typing import Any, cast

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    ClientProfile,
    OAuthAccount,
    OAuthProvider,
    PsychologistProfile,
    User,
    UserRole,
)
from app.schemas.auth import TokenResponse
from app.services import auth_service, token_service

settings = get_settings()
logger = logging.getLogger(__name__)

_STATE_PREFIX = "oauth:state:"
_USER_AGENT = "mind-it-backend"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


@dataclass(frozen=True, slots=True)
class _ProviderEndpoints:
    """Адреса OAuth2-провайдера и запрашиваемые scopes."""

    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Полная конфигурация провайдера для конкретного запроса."""

    provider: OAuthProvider
    client_id: str
    client_secret: str
    redirect_uri: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Нормализованный профиль из ответа провайдера."""

    provider_user_id: str
    email: str
    email_verified: bool
    display_name: str | None = None


_ENDPOINTS: dict[OAuthProvider, _ProviderEndpoints] = {
    OAuthProvider.YANDEX: _ProviderEndpoints(
        authorize_url="https://oauth.yandex.ru/authorize",
        token_url="https://oauth.yandex.ru/token",
        userinfo_url="https://login.yandex.ru/info?format=json",
        scope="login:email login:info",
    ),
    OAuthProvider.GOOGLE: _ProviderEndpoints(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
    ),
    OAuthProvider.GITHUB: _ProviderEndpoints(
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
    ),
}


def _provider_config(provider: OAuthProvider) -> ProviderConfig:
    """Собрать конфигурацию провайдера или вернуть понятную ошибку."""
    endpoints = _ENDPOINTS[provider]

    if provider is OAuthProvider.YANDEX:
        client_id = settings.yandex_client_id
        client_secret = settings.yandex_client_secret
        redirect_uri = settings.yandex_redirect_uri
    elif provider is OAuthProvider.GOOGLE:
        client_id = settings.google_client_id
        client_secret = settings.google_client_secret
        redirect_uri = settings.google_redirect_uri
    else:
        client_id = settings.github_client_id
        client_secret = settings.github_client_secret
        redirect_uri = settings.github_redirect_uri

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="oauth_provider_not_configured",
        )

    return ProviderConfig(
        provider=provider,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        authorize_url=endpoints.authorize_url,
        token_url=endpoints.token_url,
        userinfo_url=endpoints.userinfo_url,
        scope=endpoints.scope,
    )


def _oauth_client(config: ProviderConfig) -> Any:
    """Создать authlib-клиент с настройками провайдера."""
    return AsyncOAuth2Client(
        client_id=config.client_id,
        client_secret=config.client_secret,
        scope=config.scope,
        redirect_uri=config.redirect_uri,
    )


async def create_authorize_url(redis: Redis, provider: OAuthProvider) -> str:
    """Сгенерировать одноразовый state и URL авторизации провайдера."""
    config = _provider_config(provider)
    state = secrets.token_urlsafe(32)
    await redis.set(
        f"{_STATE_PREFIX}{state}",
        provider.value,
        ex=settings.oauth_state_ttl_minutes * 60,
    )

    async with _oauth_client(config) as client:
        url, _ = client.create_authorization_url(config.authorize_url, state=state)
    return cast(str, url)


async def complete_callback(
    db: AsyncSession,
    redis: Redis,
    provider: OAuthProvider,
    *,
    code: str,
    state: str,
    user_agent: str | None,
    ip_address: str | None,
) -> TokenResponse:
    """Проверить state, обменять код и войти (или создать) пользователя."""
    config = _provider_config(provider)
    stored_provider = cast(str | None, await redis.getdel(f"{_STATE_PREFIX}{state}"))
    if stored_provider != provider.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_oauth_state",
        )

    profile = await _fetch_profile(config, code)
    user = await _resolve_user(db, provider, profile)
    tokens = await token_service.create_session(db, user, user_agent, ip_address)
    await db.commit()

    logger.info("OAuth login via %s for %s", provider.value, user.email)
    return tokens


async def _fetch_profile(config: ProviderConfig, code: str) -> ProviderProfile:
    """Обменять authorization code на токен и получить профиль."""
    async with _oauth_client(config) as client:
        try:
            token: Any = await client.fetch_token(
                config.token_url,
                code=code,
                grant_type="authorization_code",
                headers={"Accept": "application/json"},
            )
        except OAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="oauth_exchange_failed",
            ) from exc

        if not isinstance(token, dict) or not token.get("access_token"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="oauth_profile_unavailable",
            )

        response = await client.get(
            config.userinfo_url,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "OAuth profile request failed (%s): %s",
                config.provider.value,
                response.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="oauth_profile_unavailable",
            )

        data = cast(dict[str, Any], response.json())
        if config.provider is OAuthProvider.GITHUB:
            return await _github_profile(client, data)
        if config.provider is OAuthProvider.GOOGLE:
            return _google_profile(data)
        return _yandex_profile(data)


def _yandex_profile(data: dict[str, Any]) -> ProviderProfile:
    """Разобрать ответ `login.yandex.ru/info`."""
    provider_user_id = data.get("id")
    email = data.get("default_email")
    if not email:
        emails = data.get("emails")
        if isinstance(emails, list) and emails:
            email = emails[0]
    if provider_user_id is None or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="oauth_profile_unavailable",
        )

    display_name = data.get("first_name") or data.get("display_name")
    return ProviderProfile(
        provider_user_id=str(provider_user_id),
        email=auth_service.normalize_email(email),
        email_verified=True,
        display_name=display_name if isinstance(display_name, str) else None,
    )


def _google_profile(data: dict[str, Any]) -> ProviderProfile:
    """Разобрать ответ Google OpenID Connect `userinfo`."""
    provider_user_id = data.get("sub")
    email = data.get("email")
    if provider_user_id is None or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="oauth_profile_unavailable",
        )
    if data.get("email_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth_email_unverified",
        )

    display_name = data.get("given_name") or data.get("name")
    return ProviderProfile(
        provider_user_id=str(provider_user_id),
        email=auth_service.normalize_email(email),
        email_verified=True,
        display_name=display_name if isinstance(display_name, str) else None,
    )


async def _github_profile(
    client: Any,
    data: dict[str, Any],
) -> ProviderProfile:
    """Разобрать профиль GitHub, выбрав подтверждённый primary-email."""
    provider_user_id = data.get("id")
    if provider_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="oauth_profile_unavailable",
        )

    response = await client.get(
        _GITHUB_EMAILS_URL,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="oauth_profile_unavailable",
        )

    raw_emails = response.json()
    if not isinstance(raw_emails, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="oauth_profile_unavailable",
        )

    emails: list[dict[str, Any]] = [
        cast(dict[str, Any], item) for item in raw_emails if isinstance(item, dict)
    ]
    verified = [
        item
        for item in emails
        if item.get("verified") is True and isinstance(item.get("email"), str)
    ]
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth_email_unverified",
        )

    primary = next((item for item in verified if item.get("primary") is True), verified[0])
    email = cast(str, primary["email"])

    display_name = data.get("name") or data.get("login")
    return ProviderProfile(
        provider_user_id=str(provider_user_id),
        email=auth_service.normalize_email(email),
        email_verified=True,
        display_name=display_name if isinstance(display_name, str) else None,
    )


async def _resolve_user(
    db: AsyncSession,
    provider: OAuthProvider,
    profile: ProviderProfile,
) -> User:
    """Найти/создать пользователя и привязать OAuth-аккаунт."""
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == profile.provider_user_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is not None:
        user = await db.get(User, account.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_oauth_account",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user_inactive",
            )
        if account.provider_email != profile.email:
            account.provider_email = profile.email
        return user

    existing = await auth_service.get_user_by_email(db, profile.email)
    if existing is not None:
        if not existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user_inactive",
            )

        # Провайдер подтвердил владение email — доверяем этому.
        existing.email_verified = True
        db.add(
            OAuthAccount(
                user_id=existing.id,
                provider=provider,
                provider_user_id=profile.provider_user_id,
                provider_email=profile.email,
            )
        )
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="oauth_account_conflict",
            ) from exc
        return existing

    user = User(
        email=profile.email,
        password_hash=None,
        role=UserRole.CLIENT,
        email_verified=True,
        role_selected=False,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_taken",
        ) from exc

    db.add(
        ClientProfile(
            user_id=user.id,
            first_name=profile.display_name,
        )
    )
    db.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=profile.provider_user_id,
            provider_email=profile.email,
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="oauth_account_conflict",
        ) from exc

    logger.info("Created user %s from %s OAuth", user.email, provider.value)
    return user


async def set_role(db: AsyncSession, user: User, role: UserRole) -> User:
    """Выбрать роль один раз после OAuth-регистрации и создать профиль."""
    if role is UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_role",
        )

    if user.role_selected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="role_already_selected",
        )

    await _ensure_profile(db, user, role)
    user.role = role
    user.role_selected = True
    await db.commit()

    logger.info("User %s selected role %s", user.email, role.value)
    return user


async def _ensure_profile(db: AsyncSession, user: User, role: UserRole) -> None:
    """Оставить ровно один профиль, соответствующий выбранной роли."""
    if role is UserRole.PSYCHOLOGIST:
        client_profile = await db.get(ClientProfile, user.id)
        if client_profile is not None:
            await db.delete(client_profile)
            await db.flush()
        if await db.get(PsychologistProfile, user.id) is None:
            db.add(
                PsychologistProfile(
                    user_id=user.id,
                    first_name=auth_service.default_first_name(user.email),
                )
            )
        return

    psychologist_profile = await db.get(PsychologistProfile, user.id)
    if psychologist_profile is not None:
        await db.delete(psychologist_profile)
        await db.flush()
    if await db.get(ClientProfile, user.id) is None:
        db.add(ClientProfile(user_id=user.id))
