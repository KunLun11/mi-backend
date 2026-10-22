"""Тесты дашборда клиента: заявки, отмена и сессии."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient

from app.database import SessionFactory
from app.models import (
    ClientProfile,
    Concern,
    PsychologistProfile,
    PsychologistStatus,
    RequestStatus,
    SessionRequest,
    TherapySession,
    TherapyStatus,
    User,
    UserRole,
)
from app.schemas.quizzes import RecommendationCreate
from app.services import recommendation_service, token_service

API = "/api/v1"


async def _create_user(
    email: str,
    role: UserRole,
    *,
    first_name: str = "Психолог",
    status: PsychologistStatus = PsychologistStatus.APPROVED,
) -> tuple[UUID, dict[str, str]]:
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
        elif role is UserRole.PSYCHOLOGIST:
            db.add(
                PsychologistProfile(
                    user_id=user.id,
                    first_name=first_name,
                    status=status,
                    session_price_rub=3000,
                )
            )
        await db.flush()

        tokens = await token_service.create_session(db, user, None, None)
        await db.commit()
        user_id = user.id

    return user_id, {"Authorization": f"Bearer {tokens.access_token}"}


async def _create_request(
    client: AsyncClient,
    client_headers: dict[str, str],
    psychologist_id: UUID,
) -> dict:
    async with SessionFactory() as db:
        concern = Concern(slug="burnout", name="Выгорание")
        db.add(concern)
        await db.commit()
        await db.refresh(concern)
        concern_id = concern.id

    response = await client.post(
        f"{API}/quizzes",
        headers=client_headers,
        json={
            "role_in_it": "developer",
            "primary_concern_id": concern_id,
            "preferred_format": "online",
            "preferred_price_max": 5000,
        },
    )
    assert response.status_code == 201, response.text
    quiz_id = UUID(response.json()["id"])

    async with SessionFactory() as db:
        await recommendation_service.create_recommendation(
            db,
            RecommendationCreate(
                quiz_id=quiz_id,
                psychologist_id=psychologist_id,
                admin_note="Подходит по опыту",
            ),
        )

    recommendations_response = await client.get(
        f"{API}/quizzes/{quiz_id}/recommendations",
        headers=client_headers,
    )
    assert recommendations_response.status_code == 200, recommendations_response.text
    recommendation = recommendations_response.json()[0]

    response = await client.post(
        f"{API}/session-requests",
        headers=client_headers,
        json={
            "recommendation_id": recommendation["id"],
            "message": "Хочу разобраться с выгоранием",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_client_sees_request_and_can_cancel(client: AsyncClient) -> None:
    client_id, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user(
        "psy@example.com",
        UserRole.PSYCHOLOGIST,
        first_name="Марина",
    )

    request = await _create_request(client, client_headers, psychologist_id)
    assert request["psychologist"]["first_name"] == "Марина"
    assert request["client"]["user_id"] == str(client_id)
    assert request["client"]["timezone"] == "Europe/Moscow"

    response = await client.get(f"{API}/session-requests", headers=client_headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == request["id"]
    assert items[0]["status"] == "pending"
    assert items[0]["psychologist"]["session_price_rub"] == 3000

    response = await client.get(f"{API}/session-requests", headers=psy_headers)
    assert response.status_code == 200, response.text
    incoming = response.json()
    assert len(incoming) == 1
    assert incoming[0]["client"]["user_id"] == str(client_id)

    response = await client.post(
        f"{API}/session-requests/{request['id']}/cancel",
        headers=client_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    response = await client.post(
        f"{API}/session-requests/{request['id']}/cancel",
        headers=client_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_request_status"

    async with SessionFactory() as db:
        stored = await db.get(SessionRequest, UUID(request["id"]))
    assert stored is not None and stored.status.value == "cancelled"


async def test_foreign_request_is_hidden(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    _, other_headers = await _create_user("other@example.com", UserRole.CLIENT)
    psychologist_id, _ = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)

    response = await client.get(f"{API}/session-requests", headers=other_headers)
    assert response.status_code == 200
    assert response.json() == []

    response = await client.post(
        f"{API}/session-requests/{request['id']}/cancel",
        headers=other_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "request_not_found"


async def test_psychologist_must_be_approved(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    _, psy_headers = await _create_user(
        "psy@example.com",
        UserRole.PSYCHOLOGIST,
        status=PsychologistStatus.PENDING,
    )

    response = await client.get(f"{API}/session-requests", headers=psy_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "psychologist_not_approved"

    response = await client.get(f"{API}/sessions", headers=psy_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "psychologist_not_approved"


async def test_sessions_are_visible_to_participants(client: AsyncClient) -> None:
    client_id, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    _, other_headers = await _create_user("other@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user(
        "psy@example.com",
        UserRole.PSYCHOLOGIST,
        first_name="Марина",
    )

    request = await _create_request(client, client_headers, psychologist_id)
    scheduled_at = datetime.now(UTC) + timedelta(days=3)

    async with SessionFactory() as db:
        session = TherapySession(
            request_id=UUID(request["id"]),
            client_id=client_id,
            psychologist_id=psychologist_id,
            scheduled_at=scheduled_at,
            price_rub=4000,
        )
        db.add(session)
        await db.commit()
        session_id = session.id

    response = await client.get(f"{API}/sessions", headers=client_headers)
    assert response.status_code == 200, response.text
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == str(session_id)
    assert sessions[0]["status"] == "scheduled"
    assert sessions[0]["price_rub"] == 4000
    assert sessions[0]["psychologist"]["first_name"] == "Марина"

    response = await client.get(f"{API}/sessions", headers=psy_headers)
    assert response.status_code == 200, response.text
    psychologist_sessions = response.json()
    assert len(psychologist_sessions) == 1
    assert psychologist_sessions[0]["client"]["user_id"] == str(client_id)

    response = await client.get(f"{API}/sessions", headers=other_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_cancel_accepted_request_cancels_session(client: AsyncClient) -> None:
    client_id, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, _ = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)

    async with SessionFactory() as db:
        stored = await db.get(SessionRequest, UUID(request["id"]))
        assert stored is not None
        stored.status = RequestStatus.ACCEPTED
        session = TherapySession(
            request_id=stored.id,
            client_id=client_id,
            psychologist_id=psychologist_id,
            scheduled_at=datetime.now(UTC) + timedelta(days=2),
            price_rub=3500,
        )
        db.add(session)
        await db.commit()
        session_id = session.id

    response = await client.post(
        f"{API}/session-requests/{request['id']}/cancel",
        headers=client_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    async with SessionFactory() as db:
        stored_session = await db.get(TherapySession, session_id)
    assert stored_session is not None
    assert stored_session.status is TherapyStatus.CANCELLED
