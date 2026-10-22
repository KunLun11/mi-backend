"""Бизнес-логика квиза: создание, чтение и ручные рекомендации."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Concern,
    PsychologistProfile,
    QuizResponse,
    QuizStatus,
    Recommendation,
    User,
)
from app.schemas.profiles import PsychologistPublic
from app.schemas.quizzes import QuizIn, RecommendationOut


async def create_quiz(db: AsyncSession, user: User, data: QuizIn) -> QuizResponse:
    """Создать квиз клиента в статусе `submitted`."""
    concern = await db.get(Concern, data.primary_concern_id)
    if concern is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown_concern",
        )

    quiz = QuizResponse(
        client_id=user.id,
        role_in_it=data.role_in_it,
        primary_concern_id=data.primary_concern_id,
        preferred_format=data.preferred_format,
        preferred_price_max=data.preferred_price_max,
        free_text=data.free_text,
        status=QuizStatus.SUBMITTED,
    )
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    return quiz


async def get_quiz(db: AsyncSession, user: User, quiz_id: UUID) -> QuizResponse:
    """Вернуть квиз клиента или 404, если он чужой/не существует."""
    quiz = await db.get(QuizResponse, quiz_id)
    if quiz is None or quiz.client_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="quiz_not_found",
        )
    return quiz


async def _load_profiles(
    db: AsyncSession,
    user_ids: list[UUID],
) -> dict[UUID, PsychologistProfile]:
    """Загрузить публичные профили психологов одним запросом."""
    if not user_ids:
        return {}

    result = await db.execute(
        select(PsychologistProfile)
        .where(PsychologistProfile.user_id.in_(user_ids))
        .options(
            selectinload(PsychologistProfile.approaches),
            selectinload(PsychologistProfile.it_contexts),
        )
    )
    return {profile.user_id: profile for profile in result.scalars()}


async def list_recommendations(
    db: AsyncSession,
    user: User,
    quiz_id: UUID,
) -> list[RecommendationOut]:
    """Вернуть рекомендации по квизу (только в статусе `recommended`)."""
    quiz = await get_quiz(db, user, quiz_id)
    if quiz.status is not QuizStatus.RECOMMENDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="quiz_not_ready",
        )

    result = await db.execute(
        select(Recommendation)
        .where(Recommendation.quiz_id == quiz.id)
        .order_by(Recommendation.rank, Recommendation.created_at)
    )
    recommendations = list(result.scalars().all())

    profiles = await _load_profiles(
        db,
        [item.psychologist_id for item in recommendations],
    )

    output: list[RecommendationOut] = []
    for item in recommendations:
        profile = profiles.get(item.psychologist_id)
        if profile is None:
            continue
        output.append(
            RecommendationOut(
                id=item.id,
                quiz_id=item.quiz_id,
                rank=item.rank,
                admin_note=item.admin_note,
                psychologist=PsychologistPublic.model_validate(profile),
            )
        )
    return output
