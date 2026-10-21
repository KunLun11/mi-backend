"""E2E-тесты аутентификации: регистрация → verify → login → refresh → logout."""

import asyncio
import base64
import re
from typing import Any

import httpx
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionFactory
from app.models import EmailVerificationCode, User

API = "/api/v1/auth"
MAILHOG_URL = "http://localhost:8025"
PASSWORD = "s3cret-pass"


async def _clear_mailhog() -> None:
    async with httpx.AsyncClient(base_url=MAILHOG_URL, timeout=10) as client:
        response = await client.delete("/api/v1/messages")
        response.raise_for_status()


def _decode_mime_body(part: dict[str, Any]) -> str:
    """Декодировать тело MIME-части (Mailhog отдаёт base64 для UTF-8)."""
    body = str(part.get("Body", ""))
    encodings = part.get("Headers", {}).get("Content-Transfer-Encoding", [])
    if any(str(encoding).lower() == "base64" for encoding in encodings):
        try:
            return base64.b64decode(body).decode("utf-8", errors="replace")
        except ValueError:
            return body
    return body


def _extract_code(item: dict[str, Any]) -> str | None:
    """Найти 6-значный код в MIME-частях или сыром теле письма."""
    for part in item.get("MIME", {}).get("Parts", []):
        match = re.search(r"\b(\d{6})\b", _decode_mime_body(part))
        if match:
            return match.group(1)

    match = re.search(r"\b(\d{6})\b", str(item.get("Content", {}).get("Body", "")))
    return match.group(1) if match else None


async def _fetch_code(email: str) -> str:
    async with httpx.AsyncClient(base_url=MAILHOG_URL, timeout=10) as client:
        for _ in range(50):
            response = await client.get("/api/v2/messages", params={"limit": 50})
            response.raise_for_status()
            matches: list[tuple[str, str]] = []
            for item in response.json().get("items", []):
                recipients = {
                    f"{entry.get('Mailbox', '')}@{entry.get('Domain', '')}".lower()
                    for entry in item.get("To", [])
                }
                if email.lower() not in recipients:
                    continue
                code = _extract_code(item)
                if code is not None:
                    matches.append((str(item.get("Created", "")), code))
            if matches:
                # Самое свежее письмо (Mailhog может отдавать в любом порядке).
                return max(matches)[1]
            await asyncio.sleep(0.1)

    raise AssertionError(f"verification email for {email} not found in Mailhog")


async def _register(client: AsyncClient, email: str, role: str = "client") -> None:
    response = await client.post(
        f"{API}/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )
    assert response.status_code == 204, response.text


async def _verify(client: AsyncClient, email: str) -> dict[str, object]:
    code = await _fetch_code(email)
    response = await client.post(
        f"{API}/verify-email",
        json={"email": email, "code": code},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_email_auth_happy_path_and_logout(client: AsyncClient) -> None:
    await _clear_mailhog()
    email = "client@example.com"

    await _register(client, email)

    # Пароль хранится Argon2-хешем.
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        code_hash = await session.scalar(select(EmailVerificationCode.code_hash))
    assert user is not None
    assert user.password_hash is not None
    assert user.password_hash.startswith("$argon2")
    assert code_hash is not None
    assert re.fullmatch(r"[0-9a-f]{64}", code_hash)

    # До подтверждения email вход запрещён.
    response = await client.post(
        f"{API}/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "email_not_verified"

    # Неверный код отклоняется.
    response = await client.post(
        f"{API}/verify-email",
        json={"email": email, "code": "000000"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_code"

    tokens = await _verify(client, email)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 45 * 60

    response = await client.get(f"{API}/me", headers=_bearer(str(tokens["access_token"])))
    assert response.status_code == 200, response.text
    me = response.json()
    assert me["email"] == email
    assert me["role"] == "client"
    assert me["email_verified"] is True
    assert me["profile"]["timezone"] == "Europe/Moscow"

    # Login выдаёт новую сессию.
    response = await client.post(
        f"{API}/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    login_tokens = response.json()

    # Refresh ротирует токен.
    response = await client.post(
        f"{API}/refresh",
        json={"refresh_token": login_tokens["refresh_token"]},
    )
    assert response.status_code == 200, response.text
    rotated = response.json()
    assert rotated["refresh_token"] != login_tokens["refresh_token"]

    # Logout отзывает сессию и blacklist'ит access-токен.
    response = await client.post(
        f"{API}/logout",
        json={"refresh_token": rotated["refresh_token"]},
        headers=_bearer(str(rotated["access_token"])),
    )
    assert response.status_code == 204

    response = await client.get(f"{API}/me", headers=_bearer(str(rotated["access_token"])))
    assert response.status_code == 401
    assert response.json()["detail"] == "token_revoked"

    response = await client.post(
        f"{API}/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert response.status_code == 401


async def test_refresh_reuse_revokes_whole_family(client: AsyncClient) -> None:
    await _clear_mailhog()
    email = "reuse@example.com"

    await _register(client, email)
    tokens = await _verify(client, email)

    response = await client.post(
        f"{API}/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 200, response.text
    rotated = response.json()

    # Повторное использование старого refresh-токена.
    response = await client.post(
        f"{API}/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 401

    # Всё семейство отозвано — актуальный токен тоже не работает.
    response = await client.post(
        f"{API}/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert response.status_code == 401

    # Новый вход создаёт новое семейство.
    response = await client.post(
        f"{API}/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def test_psychologist_registration_creates_draft_profile(client: AsyncClient) -> None:
    await _clear_mailhog()
    email = "psy@example.com"

    await _register(client, email, role="psychologist")
    tokens = await _verify(client, email)

    response = await client.get(f"{API}/me", headers=_bearer(str(tokens["access_token"])))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "psychologist"
    assert body["profile"]["first_name"] == "psy"
    assert body["profile"]["status"] == "draft"


async def test_resend_code_is_rate_limited(client: AsyncClient) -> None:
    await _clear_mailhog()
    email = "resend@example.com"

    await _register(client, email)

    response = await client.post(f"{API}/resend-code", json={"email": email})
    assert response.status_code == 204

    response = await client.post(f"{API}/resend-code", json={"email": email})
    assert response.status_code == 429
    assert response.json()["detail"] == "rate_limit_exceeded"

    # Новый код из второго письма позволяет подтвердить email.
    tokens = await _verify(client, email)
    assert tokens["access_token"]
