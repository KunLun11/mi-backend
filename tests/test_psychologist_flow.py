"""Тесты психолога: accept/decline заявок, complete/no-show сессий."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionFactory
from app.models import (
    ClientProfile,
    Commission,
    CommissionStatus,
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


async def _accept(
    client: AsyncClient,
    psy_headers: dict[str, str],
    request_id: str,
    *,
    price_rub: int = 4000,
) -> dict:
    scheduled_at = datetime.now(UTC) + timedelta(days=3)
    response = await client.post(
        f"{API}/session-requests/{request_id}/accept",
        headers=psy_headers,
        json={"scheduled_at": scheduled_at.isoformat(), "price_rub": price_rub},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_accept_creates_session_visible_to_both(client: AsyncClient) -> None:
    client_id, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user(
        "psy@example.com",
        UserRole.PSYCHOLOGIST,
        first_name="Марина",
    )

    request = await _create_request(client, client_headers, psychologist_id)
    session = await _accept(client, psy_headers, request["id"])

    assert session["status"] == "scheduled"
    assert session["price_rub"] == 4000
    assert session["client_id"] == str(client_id)
    assert session["psychologist_id"] == str(psychologist_id)
    assert session["client"]["user_id"] == str(client_id)

    response = await client.get(f"{API}/session-requests", headers=psy_headers)
    assert response.status_code == 200, response.text
    assert response.json()[0]["status"] == "accepted"

    response = await client.get(f"{API}/sessions", headers=client_headers)
    assert response.status_code == 200, response.text
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session["id"]
    assert sessions[0]["psychologist"]["first_name"] == "Марина"

    response = await client.get(f"{API}/sessions", headers=psy_headers)
    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == session["id"]


async def test_decline_request(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)

    response = await client.post(
        f"{API}/session-requests/{request['id']}/decline",
        headers=psy_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "declined"

    response = await client.post(
        f"{API}/session-requests/{request['id']}/accept",
        headers=psy_headers,
        json={"scheduled_at": datetime.now(UTC).isoformat(), "price_rub": 3000},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_request_status"

    async with SessionFactory() as db:
        stored = await db.get(SessionRequest, UUID(request["id"]))
    assert stored is not None and stored.status is RequestStatus.DECLINED


async def test_foreign_psychologist_cannot_accept(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, _ = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)
    _, other_headers = await _create_user("other@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)

    response = await client.post(
        f"{API}/session-requests/{request['id']}/accept",
        headers=other_headers,
        json={"scheduled_at": datetime.now(UTC).isoformat(), "price_rub": 3000},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "request_not_found"


async def test_pending_psychologist_cannot_accept(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)
    request = await _create_request(client, client_headers, psychologist_id)

    async with SessionFactory() as db:
        profile = await db.get(PsychologistProfile, psychologist_id)
        assert profile is not None
        profile.status = PsychologistStatus.PENDING
        await db.commit()

    response = await client.post(
        f"{API}/session-requests/{request['id']}/accept",
        headers=psy_headers,
        json={"scheduled_at": datetime.now(UTC).isoformat(), "price_rub": 3000},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "psychologist_not_approved"


async def test_complete_creates_commission(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)
    session = await _accept(client, psy_headers, request["id"], price_rub=4000)

    response = await client.post(
        f"{API}/sessions/{session['id']}/complete",
        headers=psy_headers,
    )
    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None

    async with SessionFactory() as db:
        stored = await db.get(SessionRequest, UUID(request["id"]))
        stored_commission = await db.scalar(
            select(Commission).where(Commission.session_id == UUID(session["id"]))
        )
    assert stored is not None and stored.status is RequestStatus.COMPLETED
    assert stored_commission is not None
    assert stored_commission.amount_rub == 500
    assert stored_commission.status is CommissionStatus.PENDING

    response = await client.post(
        f"{API}/sessions/{session['id']}/complete",
        headers=psy_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_session_status"


async def test_no_show_marks_session(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, psy_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)

    request = await _create_request(client, client_headers, psychologist_id)
    session = await _accept(client, psy_headers, request["id"])

    response = await client.post(
        f"{API}/sessions/{session['id']}/no-show",
        headers=psy_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "no_show"

    async with SessionFactory() as db:
        stored = await db.get(TherapySession, UUID(session["id"]))
    assert stored is not None and stored.status is TherapyStatus.NO_SHOW
