"""Тесты профилей клиента/психолога, модерации и каталога психологов."""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import func, select

from app.database import SessionFactory
from app.models import (
    Approach,
    ClientProfile,
    Concern,
    ITContextTag,
    PsychologistProfile,
    PsychologistStatus,
    User,
    UserRole,
)
from app.models.enums import Format
from app.services import token_service
from scripts.seed_dicts import seed_dictionaries

API = "/api/v1"


async def _create_user(
    email: str,
    role: UserRole,
    *,
    status: PsychologistStatus | None = None,
) -> tuple[UUID, dict[str, str]]:
    """Создать подтверждённого пользователя с профилем и выдать access-токен."""
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

        if role is UserRole.CLIENT:
            db.add(ClientProfile(user_id=user.id))
        else:
            db.add(
                PsychologistProfile(
                    user_id=user.id,
                    first_name="Психолог",
                    status=status or PsychologistStatus.DRAFT,
                )
            )
        await db.flush()

        tokens = await token_service.create_session(db, user, None, None)
        await db.commit()
        user_id = user.id

    return user_id, {"Authorization": f"Bearer {tokens.access_token}"}


async def _seed_approaches_and_contexts() -> tuple[Approach, Approach, ITContextTag, ITContextTag]:
    async with SessionFactory() as db:
        cbt = Approach(slug="cbt", name="КПТ")
        gestalt = Approach(slug="gestalt", name="Гештальт-терапия")
        burnout = ITContextTag(slug="burnout", name="Выгорание")
        managers = ITContextTag(slug="manager_stress", name="Стресс руководителя")
        db.add_all([cbt, gestalt, burnout, managers])
        await db.commit()
        return cbt, gestalt, burnout, managers


async def test_client_profile_read_and_update(client: AsyncClient) -> None:
    user_id, headers = await _create_user("client@example.com", UserRole.CLIENT)

    response = await client.get(f"{API}/clients/me", headers=headers)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["first_name"] is None
    assert created["timezone"] == "Europe/Moscow"
    assert created["preferred_format"] == "online"
    assert created["user_id"] == str(user_id)

    response = await client.put(
        f"{API}/clients/me",
        headers=headers,
        json={
            "first_name": "Анна",
            "timezone": "Asia/Yekaterinburg",
            "preferred_format": "both",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Анна"
    assert body["timezone"] == "Asia/Yekaterinburg"
    assert body["preferred_format"] == "both"

    # Значения сохранились.
    response = await client.get(f"{API}/clients/me", headers=headers)
    assert response.json()["first_name"] == "Анна"

    # Невалидный часовой пояс отклоняется схемой.
    response = await client.put(
        f"{API}/clients/me",
        headers=headers,
        json={"timezone": "not a timezone!"},
    )
    assert response.status_code == 422

    # Чужая роль не имеет доступа к профилю клиента.
    _, psychologist_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)
    response = await client.get(f"{API}/clients/me", headers=psychologist_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


async def test_psychologist_profile_update_and_submit(client: AsyncClient) -> None:
    cbt, _, burnout, managers = await _seed_approaches_and_contexts()
    _, headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    response = await client.get(f"{API}/psychologists/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"
    assert response.json()["formats"] == ["online"]
    assert response.json()["approaches"] == []

    # /auth/me отдаёт тот же профиль психолога.
    response = await client.get(f"{API}/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["status"] == "draft"
    assert response.json()["profile"]["formats"] == ["online"]

    response = await client.put(
        f"{API}/psychologists/me",
        headers=headers,
        json={
            "first_name": "Мария",
            "last_name": "Иванова",
            "bio": "Работаю с выгоранием в IT.",
            "education": "МГУ, клиническая психология",
            "years_experience": 7,
            "session_price_rub": 4000,
            "formats": ["online", "offline", "online"],
            "approach_ids": [cbt.id],
            "it_context_ids": [burnout.id, managers.id],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Мария"
    assert body["years_experience"] == 7
    assert body["session_price_rub"] == 4000
    assert body["formats"] == ["online", "offline"]
    assert [item["slug"] for item in body["approaches"]] == ["cbt"]
    assert [item["slug"] for item in body["it_contexts"]] == ["burnout", "manager_stress"]

    # Неизвестный справочный ID — 400.
    response = await client.put(
        f"{API}/psychologists/me",
        headers=headers,
        json={"approach_ids": [999_999]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_approach"

    # Пустой список форматов запрещён схемой.
    response = await client.put(
        f"{API}/psychologists/me",
        headers=headers,
        json={"formats": []},
    )
    assert response.status_code == 422

    response = await client.post(f"{API}/psychologists/me/submit", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"

    # Повторная отправка на модерацию запрещена.
    response = await client.post(f"{API}/psychologists/me/submit", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_profile_status"

    # После отклонения профиль можно отправить повторно.
    async with SessionFactory() as db:
        profile = await db.get(PsychologistProfile, UUID(body["user_id"]))
        assert profile is not None
        profile.status = PsychologistStatus.REJECTED
        await db.commit()

    response = await client.post(f"{API}/psychologists/me/submit", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "pending"

    # Одобренный профиль повторно не отправляется.
    async with SessionFactory() as db:
        profile = await db.get(PsychologistProfile, UUID(body["user_id"]))
        assert profile is not None
        profile.status = PsychologistStatus.APPROVED
        await db.commit()

    response = await client.post(f"{API}/psychologists/me/submit", headers=headers)
    assert response.status_code == 409

    # Клиент не может читать профиль психолога.
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    response = await client.get(f"{API}/psychologists/me", headers=client_headers)
    assert response.status_code == 403


async def test_psychologists_catalog_filters_and_moderation(client: AsyncClient) -> None:
    cbt, gestalt, burnout, managers = await _seed_approaches_and_contexts()

    approved_a = await _create_user(
        "approved-a@example.com",
        UserRole.PSYCHOLOGIST,
        status=PsychologistStatus.APPROVED,
    )
    approved_b = await _create_user(
        "approved-b@example.com",
        UserRole.PSYCHOLOGIST,
        status=PsychologistStatus.APPROVED,
    )
    pending = await _create_user(
        "pending@example.com",
        UserRole.PSYCHOLOGIST,
        status=PsychologistStatus.PENDING,
    )

    # Заполнить профили связями и форматами.
    async with SessionFactory() as db:
        profile_a = await db.get(PsychologistProfile, approved_a[0])
        profile_b = await db.get(PsychologistProfile, approved_b[0])
        profile_pending = await db.get(PsychologistProfile, pending[0])
        assert profile_a is not None
        assert profile_b is not None
        assert profile_pending is not None

        profile_a.approaches = [cbt]
        profile_a.it_contexts = [burnout]
        profile_a.formats = [Format.ONLINE]

        profile_b.approaches = [gestalt]
        profile_b.it_contexts = [managers]
        profile_b.formats = [Format.OFFLINE]

        profile_pending.approaches = [cbt]
        await db.commit()

    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)

    response = await client.get(f"{API}/psychologists", headers=client_headers)
    assert response.status_code == 200, response.text
    listing = response.json()
    assert listing["total"] == 2
    assert {item["user_id"] for item in listing["items"]} == {
        str(approved_a[0]),
        str(approved_b[0]),
    }

    async def _ids(params: dict[str, object]) -> set[str]:
        response = await client.get(
            f"{API}/psychologists",
            headers=client_headers,
            params=params,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        return {item["user_id"] for item in payload["items"]}

    assert await _ids({"approach": "cbt"}) == {str(approved_a[0])}
    assert await _ids({"it_context": "manager_stress"}) == {str(approved_b[0])}
    assert await _ids({"format": "offline"}) == {str(approved_b[0])}
    assert await _ids({"format": "both"}) == set()
    assert await _ids({"approach": "cbt", "format": "offline"}) == set()

    # Пагинация: всего 2, по одному на страницу.
    first_page = await client.get(
        f"{API}/psychologists",
        headers=client_headers,
        params={"page": 1, "page_size": 1},
    )
    second_page = await client.get(
        f"{API}/psychologists",
        headers=client_headers,
        params={"page": 2, "page_size": 1},
    )
    third_page = await client.get(
        f"{API}/psychologists",
        headers=client_headers,
        params={"page": 3, "page_size": 1},
    )
    for page_response in (first_page, second_page):
        assert page_response.status_code == 200, page_response.text
        assert page_response.json()["total"] == 2
        assert len(page_response.json()["items"]) == 1
    assert first_page.json()["items"][0]["user_id"] != second_page.json()["items"][0]["user_id"]
    assert third_page.status_code == 200
    assert third_page.json()["items"] == []

    # Публичная карточка только для approved.
    response = await client.get(f"{API}/psychologists/{approved_a[0]}", headers=client_headers)
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["user_id"] == str(approved_a[0])
    assert "status" not in card
    assert card["formats"] == ["online"]

    response = await client.get(f"{API}/psychologists/{pending[0]}", headers=client_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "psychologist_not_found"

    # Без токена каталог недоступен.
    response = await client.get(f"{API}/psychologists")
    assert response.status_code == 401


async def test_seed_dicts_is_idempotent(client: AsyncClient) -> None:
    await seed_dictionaries()
    await seed_dictionaries()

    async with SessionFactory() as db:
        approaches = await db.scalar(select(func.count()).select_from(Approach))
        contexts = await db.scalar(select(func.count()).select_from(ITContextTag))
        concerns = await db.scalar(select(func.count()).select_from(Concern))

    assert approaches == 5
    assert contexts == 12
    assert concerns == 8
