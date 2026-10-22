"""Тесты справочников для квиза и онбординга."""

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionFactory
from app.models import Approach, Concern, ITContextTag, User, UserRole
from app.services import token_service
from scripts.seed_dicts import seed_dictionaries

API = "/api/v1"


async def _create_user(email: str, role: UserRole) -> dict[str, str]:
    async with SessionFactory() as db:
        user = User(
            email=email,
            password_hash=None,
            role=role,
            email_verified=True,
            role_selected=True,
        )
        db.add(user)
        await db.flush()
        tokens = await token_service.create_session(db, user, None, None)
        await db.commit()
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def test_dictionaries_require_auth(client: AsyncClient) -> None:
    response = await client.get(f"{API}/dictionaries/concerns")
    assert response.status_code == 401
    assert response.json()["detail"] == "not_authenticated"


async def test_dictionaries_return_seeded_items(client: AsyncClient) -> None:
    await seed_dictionaries()
    headers = await _create_user("client@example.com", UserRole.CLIENT)

    async with SessionFactory() as db:
        expected_approaches = list(await db.scalars(select(Approach)))
        expected_concerns = list(await db.scalars(select(Concern)))
        expected_contexts = list(await db.scalars(select(ITContextTag)))

    assert len(expected_approaches) >= 5
    assert len(expected_concerns) >= 8
    assert len(expected_contexts) >= 12

    for path, expected in (
        ("approaches", expected_approaches),
        ("it-contexts", expected_contexts),
        ("concerns", expected_concerns),
    ):
        response = await client.get(f"{API}/dictionaries/{path}", headers=headers)
        assert response.status_code == 200, response.text
        items = response.json()
        assert len(items) == len(expected)
        first = items[0]
        assert set(first) == {"id", "slug", "name"}
        assert isinstance(first["id"], int)
        # Порядок стабилен — по ID.
        assert [item["id"] for item in items] == sorted(item["id"] for item in items)
