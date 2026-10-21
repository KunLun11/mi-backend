"""Криптография: argon2 для паролей, SHA-256 для кодов и refresh-токенов."""

import asyncio
import hashlib
import secrets
from typing import cast

from passlib.context import CryptContext

_password_context = CryptContext(schemes=["argon2"], deprecated="auto")


async def hash_password(password: str) -> str:
    """Захешировать пароль Argon2 в отдельном потоке (CPU-bound)."""
    return cast(str, await asyncio.to_thread(_password_context.hash, password))


async def verify_password(password: str, password_hash: str) -> bool:
    """Проверить пароль по Argon2-хешу в отдельном потоке."""
    return cast(
        bool,
        await asyncio.to_thread(_password_context.verify, password, password_hash),
    )


def generate_email_code() -> str:
    """Сгенерировать 6-значный код подтверждения email."""
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_refresh_token() -> str:
    """Opaque refresh-токен: 64 случайных байта в base64url."""
    return secrets.token_urlsafe(64)


def sha256_hex(value: str) -> str:
    """SHA-256 в hex — для кодов верификации и refresh-токенов."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
