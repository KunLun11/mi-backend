"""Тесты квиза, ручных рекомендаций и заявки на сессию."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionFactory
from app.models import (
    ClientProfile,
    Concern,
    PsychologistProfile,
    PsychologistStatus,
    QuizResponse,
    Recommendation,
    SessionRequest,
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
        else:
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


async def _create_concern() -> Concern:
    async with SessionFactory() as db:
        concern = Concern(slug="burnout", name="Выгорание")
        db.add(concern)
        await db.commit()
        await db.refresh(concern)
        return concern


async def _create_quiz(client: AsyncClient, headers: dict[str, str], concern_id: int) -> dict:
    response = await client.post(
        f"{API}/quizzes",
        headers=headers,
        json={
            "role_in_it": "developer",
            "primary_concern_id": concern_id,
            "preferred_format": "online",
            "preferred_price_max": 5000,
            "free_text": "  Полгода в режиме релизов.  ",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _recommend(quiz_id: UUID, psychologist_id: UUID, note: str = "Подходит по опыту") -> None:
    async with SessionFactory() as db:
        await recommendation_service.create_recommendation(
            db,
            RecommendationCreate(
                quiz_id=quiz_id,
                psychologist_id=psychologist_id,
                admin_note=note,
            ),
        )


async def test_quiz_recommendation_and_request_flow(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, _ = await _create_user(
        "psy@example.com",
        UserRole.PSYCHOLOGIST,
        first_name="Марина",
    )
    concern = await _create_concern()

    quiz = await _create_quiz(client, client_headers, concern.id)
    quiz_id = UUID(quiz["id"])
    assert quiz["status"] == "submitted"
    assert quiz["free_text"] == "Полгода в режиме релизов."
    assert quiz["preferred_price_max"] == 5000

    response = await client.get(f"{API}/quizzes/{quiz_id}", headers=client_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted"

    response = await client.get(
        f"{API}/quizzes/{quiz_id}/recommendations",
        headers=client_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "quiz_not_ready"

    await _recommend(quiz_id, psychologist_id)

    response = await client.get(f"{API}/quizzes/{quiz_id}", headers=client_headers)
    assert response.json()["status"] == "recommended"

    response = await client.get(
        f"{API}/quizzes/{quiz_id}/recommendations",
        headers=client_headers,
    )
    assert response.status_code == 200, response.text
    recommendations = response.json()
    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation["admin_note"] == "Подходит по опыту"
    assert recommendation["rank"] == 1
    assert recommendation["psychologist"]["first_name"] == "Марина"
    assert recommendation["psychologist"]["session_price_rub"] == 3000

    response = await client.post(
        f"{API}/session-requests",
        headers=client_headers,
        json={
            "recommendation_id": recommendation["id"],
            "message": "Хочу разобраться с выгоранием",
            "preferred_time": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    request = response.json()
    assert request["status"] == "pending"
    assert request["recommendation_id"] == recommendation["id"]
    assert request["psychologist_id"] == str(psychologist_id)

    # Повторная заявка по той же рекомендации запрещена.
    response = await client.post(
        f"{API}/session-requests",
        headers=client_headers,
        json={"recommendation_id": recommendation["id"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "request_exists"

    async with SessionFactory() as db:
        stored_quiz = await db.get(QuizResponse, quiz_id)
        stored_requests = list(await db.scalars(select(SessionRequest)))
        stored_recommendations = list(await db.scalars(select(Recommendation)))

    assert stored_quiz is not None and stored_quiz.status.value == "recommended"
    assert len(stored_requests) == 1
    assert len(stored_recommendations) == 1


async def test_quiz_validates_concern_and_ownership(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    _, other_headers = await _create_user("other@example.com", UserRole.CLIENT)
    _, psy_headers = await _create_user("psy@example.com", UserRole.PSYCHOLOGIST)
    concern = await _create_concern()

    response = await client.post(
        f"{API}/quizzes",
        headers=client_headers,
        json={
            "role_in_it": "developer",
            "primary_concern_id": 999_999,
            "preferred_format": "online",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_concern"

    quiz = await _create_quiz(client, client_headers, concern.id)
    quiz_id = quiz["id"]

    response = await client.get(f"{API}/quizzes/{quiz_id}", headers=other_headers)
    assert response.status_code == 404

    response = await client.get(f"{API}/quizzes/{quiz_id}", headers=psy_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


async def test_recommendation_requires_approved_psychologist(client: AsyncClient) -> None:
    _, client_headers = await _create_user("client@example.com", UserRole.CLIENT)
    psychologist_id, _ = await _create_user(
        "pending@example.com",
        UserRole.PSYCHOLOGIST,
        status=PsychologistStatus.PENDING,
    )
    concern = await _create_concern()
    quiz = await _create_quiz(client, client_headers, concern.id)

    async with SessionFactory() as db:
        with pytest.raises(HTTPException) as exc_info:
            await recommendation_service.create_recommendation(
                db,
                RecommendationCreate(
                    quiz_id=UUID(quiz["id"]),
                    psychologist_id=psychologist_id,
                    admin_note="Ещё не одобрен",
                ),
            )

    assert exc_info.value.detail == "psychologist_not_approved"
