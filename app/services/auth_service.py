"""Регистрация, подтверждение email, вход и управление сессиями."""

import logging
from datetime import UTC, datetime, timedelta
from secrets import compare_digest
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import (
    generate_email_code,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.models import (
    ClientProfile,
    EmailVerificationCode,
    PsychologistProfile,
    User,
    UserRole,
)
from app.schemas.auth import (
    MeResponse,
    TokenResponse,
)
from app.schemas.profiles import ClientProfileOut, PsychologistProfileOut
from app.services import email_service, token_service

settings = get_settings()
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Текущее время UTC (aware)."""
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    """Привести email к каноническому виду для поиска и хранения."""
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Найти пользователя по email без учёта регистра."""
    result = await db.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalar_one_or_none()


def default_first_name(email: str) -> str:
    """Имя по умолчанию для профиля психолога — локальная часть email."""
    local_part = email.split("@", 1)[0].strip()
    return (local_part or "Психолог")[:100]


async def _issue_email_code(db: AsyncSession, user: User) -> str:
    """Погасить прежние коды и создать новый (хранится только хеш)."""
    now = utcnow()
    await db.execute(
        update(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )

    code = generate_email_code()
    db.add(
        EmailVerificationCode(
            user_id=user.id,
            code_hash=sha256_hex(code),
            expires_at=now + timedelta(minutes=settings.email_code_ttl_minutes),
        )
    )
    return code


async def register(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    role: UserRole,
) -> None:
    """Создать пользователя, профиль и отправить код подтверждения."""
    if role is UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_role",
        )

    normalized_email = normalize_email(email)
    if await get_user_by_email(db, normalized_email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_taken",
        )

    user = User(
        email=normalized_email,
        password_hash=await hash_password(password),
        role=role,
        email_verified=False,
        role_selected=True,
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

    if role is UserRole.PSYCHOLOGIST:
        db.add(
            PsychologistProfile(
                user_id=user.id,
                first_name=default_first_name(normalized_email),
            )
        )
    else:
        db.add(ClientProfile(user_id=user.id))

    code = await _issue_email_code(db, user)
    try:
        await email_service.send_verification_code(normalized_email, code)
    except email_service.EmailDeliveryError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="email_send_failed",
        ) from exc

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_taken",
        ) from exc

    logger.info("Registered user %s (role=%s)", normalized_email, role.value)


async def verify_email(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    user_agent: str | None,
    ip_address: str | None,
) -> TokenResponse:
    """Проверить код, подтвердить email и выдать токены."""
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_code",
        )

    now = utcnow()
    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.consumed_at.is_(None),
            EmailVerificationCode.expires_at > now,
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if record is None or not compare_digest(record.code_hash, sha256_hex(code)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_code",
        )

    record.consumed_at = now
    user.email_verified = True
    tokens = await token_service.create_session(db, user, user_agent, ip_address)
    await db.commit()

    logger.info("Email verified for %s", user.email)
    return tokens


async def resend_code(db: AsyncSession, *, email: str) -> None:
    """Отправить новый код подтверждения (без раскрытия существования аккаунта)."""
    user = await get_user_by_email(db, email)
    if user is None:
        return

    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email_already_verified",
        )

    code = await _issue_email_code(db, user)
    try:
        await email_service.send_verification_code(user.email, code)
    except email_service.EmailDeliveryError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="email_send_failed",
        ) from exc

    await db.commit()


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None,
) -> TokenResponse:
    """Проверить учётные данные и создать новую сессию."""
    user = await get_user_by_email(db, email)
    if user is None or user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    if not await verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email_not_verified",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_inactive",
        )

    tokens = await token_service.create_session(db, user, user_agent, ip_address)
    await db.commit()

    logger.info("User logged in: %s", user.email)
    return tokens


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    """Отозвать refresh-сессию (идемпотентно)."""
    await token_service.revoke_session_by_refresh_token(db, refresh_token)
    await db.commit()


async def logout_all(db: AsyncSession, *, user_id: UUID) -> None:
    """Отозвать все сессии пользователя."""
    await token_service.revoke_all_sessions(db, user_id)
    await db.commit()


async def get_me(db: AsyncSession, user: User) -> MeResponse:
    """Собрать текущего пользователя вместе с профилем."""
    profile: ClientProfileOut | PsychologistProfileOut | None = None

    if user.role is UserRole.PSYCHOLOGIST:
        psychologist = await db.get(PsychologistProfile, user.id)
        if psychologist is not None:
            profile = PsychologistProfileOut.model_validate(psychologist)
    else:
        client = await db.get(ClientProfile, user.id)
        if client is not None:
            profile = ClientProfileOut.model_validate(client)

    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        email_verified=user.email_verified,
        role_selected=user.role_selected,
        created_at=user.created_at,
        profile=profile,
    )
