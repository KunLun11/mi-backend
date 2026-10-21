"""OAuth-флоу: authorize, callback, привязка аккаунтов и выбор роли."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionFactory
from app.models import (
    ClientProfile,
    OAuthAccount,
    OAuthProvider,
    PsychologistProfile,
    User,
    UserRole,
)
from app.services import token_service

API = "/api/v1/auth"

YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_INFO_URL = "https://login.yandex.ru/info"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_INFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


@pytest.fixture(autouse=True)
def oauth_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подставить тестовые ключи провайдеров в настройки приложения."""
    current = get_settings()
    for provider in ("yandex", "google", "github"):
        monkeypatch.setattr(current, f"{provider}_client_id", f"{provider}-client-id")
        monkeypatch.setattr(current, f"{provider}_client_secret", f"{provider}-client-secret")
        monkeypatch.setattr(
            current,
            f"{provider}_redirect_uri",
            f"http://test{API}/oauth/{provider}/callback",
        )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _authorize(client: AsyncClient, provider: OAuthProvider = OAuthProvider.YANDEX) -> str:
    """Запросить authorize URL и вернуть одноразовый state."""
    response = await client.get(f"{API}/oauth/{provider.value}/authorize")
    assert response.status_code == 200, response.text

    authorize_url = response.json()["authorize_url"]
    query = parse_qs(urlsplit(authorize_url).query)
    assert query["client_id"] == [f"{provider.value}-client-id"]
    assert query["redirect_uri"] == [f"http://test{API}/oauth/{provider.value}/callback"]
    assert "state" in query
    return query["state"][0]


async def _callback(
    client: AsyncClient,
    provider: OAuthProvider,
    state: str,
    *,
    code: str = "test-code",
) -> httpx.Response:
    return await client.get(
        f"{API}/oauth/{provider.value}/callback",
        params={"code": code, "state": state},
    )


def _mock_yandex(mock: respx.MockRouter, *, provider_user_id: str = "yandex-42") -> None:
    mock.post(YANDEX_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "yandex-access", "token_type": "bearer", "expires_in": 3600},
        )
    )
    mock.get(url__startswith=YANDEX_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": provider_user_id,
                "default_email": "oauth@example.com",
                "emails": ["oauth@example.com"],
                "first_name": "Иван",
            },
        )
    )


async def test_yandex_new_user_and_set_role(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_yandex(mock)
        state = await _authorize(client)
        response = await _callback(client, OAuthProvider.YANDEX, state)

    assert response.status_code == 200, response.text
    tokens = response.json()
    payload = token_service.decode_access_token(tokens["access_token"])

    async with SessionFactory() as db:
        user = await db.get(User, payload.sub)
        accounts = await db.scalar(select(func.count()).select_from(OAuthAccount))
        client_profile = await db.get(ClientProfile, payload.sub)

    assert user is not None
    assert user.email == "oauth@example.com"
    assert user.email_verified is True
    assert user.password_hash is None
    assert user.role is UserRole.CLIENT
    assert user.role_selected is False
    assert accounts == 1
    assert client_profile is not None
    assert client_profile.first_name == "Иван"

    response = await client.get(f"{API}/me", headers=_bearer(tokens["access_token"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "client"
    assert body["role_selected"] is False
    assert body["profile"]["first_name"] == "Иван"

    response = await client.post(
        f"{API}/set-role",
        json={"role": "psychologist"},
        headers=_bearer(tokens["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "psychologist"
    assert response.json()["role_selected"] is True

    async with SessionFactory() as db:
        assert await db.get(ClientProfile, payload.sub) is None
        psychologist_profile = await db.get(PsychologistProfile, payload.sub)

    assert psychologist_profile is not None
    assert psychologist_profile.status.value == "draft"

    response = await client.get(f"{API}/me", headers=_bearer(tokens["access_token"]))
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["status"] == "draft"

    # Роль выбирается один раз.
    response = await client.post(
        f"{API}/set-role",
        json={"role": "client"},
        headers=_bearer(tokens["access_token"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "role_already_selected"


async def test_existing_oauth_account_logs_in_same_user(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_yandex(mock)
        state = await _authorize(client)
        first = await _callback(client, OAuthProvider.YANDEX, state)
    assert first.status_code == 200, first.text
    first_sub = token_service.decode_access_token(first.json()["access_token"]).sub

    with respx.mock(assert_all_called=False) as mock:
        _mock_yandex(mock)
        state = await _authorize(client)
        second = await _callback(client, OAuthProvider.YANDEX, state)
    assert second.status_code == 200, second.text
    second_sub = token_service.decode_access_token(second.json()["access_token"]).sub

    assert second_sub == first_sub

    async with SessionFactory() as db:
        users = await db.scalar(select(func.count()).select_from(User))
        accounts = await db.scalar(select(func.count()).select_from(OAuthAccount))

    assert users == 1
    assert accounts == 1


async def test_oauth_links_to_existing_email(client: AsyncClient) -> None:
    async with SessionFactory() as db:
        user = User(
            email="oauth@example.com",
            password_hash=None,
            role=UserRole.CLIENT,
            email_verified=False,
            role_selected=True,
        )
        db.add(user)
        await db.flush()
        db.add(ClientProfile(user_id=user.id))
        await db.commit()
        user_id = user.id

    with respx.mock(assert_all_called=False) as mock:
        _mock_yandex(mock)
        state = await _authorize(client)
        response = await _callback(client, OAuthProvider.YANDEX, state)

    assert response.status_code == 200, response.text
    assert token_service.decode_access_token(response.json()["access_token"]).sub == user_id

    async with SessionFactory() as db:
        linked = await db.get(User, user_id)
        account = await db.scalar(select(OAuthAccount))

    assert linked is not None
    assert linked.email_verified is True
    assert linked.role is UserRole.CLIENT
    assert linked.role_selected is True
    assert account is not None
    assert account.user_id == user_id
    assert account.provider is OAuthProvider.YANDEX
    assert account.provider_user_id == "yandex-42"

    # Пользователь не дублируется.
    async with SessionFactory() as db:
        users = await db.scalar(select(func.count()).select_from(User))
    assert users == 1


async def test_oauth_state_is_single_use(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_yandex(mock)
        state = await _authorize(client)
        first = await _callback(client, OAuthProvider.YANDEX, state)
        assert first.status_code == 200, first.text

        replay = await _callback(client, OAuthProvider.YANDEX, state)

    assert replay.status_code == 400
    assert replay.json()["detail"] == "invalid_oauth_state"


async def test_oauth_provider_without_credentials(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "google_client_id", None)

    response = await client.get(f"{API}/oauth/google/authorize")

    assert response.status_code == 503
    assert response.json()["detail"] == "oauth_provider_not_configured"


async def test_github_uses_primary_verified_email(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(GITHUB_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "github-access", "token_type": "bearer"},
            )
        )
        mock.get(GITHUB_USER_URL).mock(
            return_value=httpx.Response(
                200,
                json={"id": 777, "email": None, "login": "octocat", "name": "Octo Cat"},
            )
        )
        mock.get(GITHUB_EMAILS_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"email": "other@example.com", "primary": False, "verified": True},
                    {"email": "octo@example.com", "primary": True, "verified": True},
                ],
            )
        )

        state = await _authorize(client, OAuthProvider.GITHUB)
        response = await _callback(client, OAuthProvider.GITHUB, state)

    assert response.status_code == 200, response.text
    sub = token_service.decode_access_token(response.json()["access_token"]).sub

    async with SessionFactory() as db:
        user = await db.get(User, sub)
        profile = await db.get(ClientProfile, sub)

    assert user is not None
    assert user.email == "octo@example.com"
    assert profile is not None
    assert profile.first_name == "Octo Cat"


async def test_google_unverified_email_is_rejected(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "google-access", "token_type": "bearer"},
            )
        )
        mock.get(GOOGLE_INFO_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sub": "google-1",
                    "email": "google@example.com",
                    "email_verified": False,
                },
            )
        )

        state = await _authorize(client, OAuthProvider.GOOGLE)
        response = await _callback(client, OAuthProvider.GOOGLE, state)

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_email_unverified"

    async with SessionFactory() as db:
        users = await db.scalar(select(func.count()).select_from(User))
    assert users == 0


async def test_oauth_error_query_is_reported(client: AsyncClient) -> None:
    response = await client.get(
        f"{API}/oauth/yandex/callback",
        params={"error": "access_denied", "state": "whatever"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_denied"
