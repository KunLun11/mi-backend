"""Тесты декодирования access-токенов: коды ошибок для фронтенда."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt

from app.config import get_settings
from app.services import token_service

settings = get_settings()


def _encode(*, expires_at: datetime, issuer: str | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "role": "client",
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": issuer or settings.jwt_issuer,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_expired_access_token_reports_token_expired() -> None:
    token = _encode(expires_at=datetime.now(UTC) - timedelta(minutes=1))

    with pytest.raises(token_service.TokenError, match="token_expired"):
        token_service.decode_access_token(token)


def test_token_with_wrong_issuer_is_invalid() -> None:
    token = _encode(
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        issuer="another-issuer",
    )

    with pytest.raises(token_service.TokenError, match="invalid_token"):
        token_service.decode_access_token(token)
