"""Создание ручных рекомендаций куратором (CLI)."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    PsychologistProfile,
    PsychologistStatus,
    QuizResponse,
    QuizStatus,
    Recommendation,
    User,
    UserRole,
)
from app.schemas.quizzes import RecommendationCreate


async def create_recommendation(
    db: AsyncSession,
    data: RecommendationCreate,
) -> Recommendation:
    """Добавить/обновить рекомендацию и перевести квиз в `recommended`."""
    quiz = await db.get(QuizResponse, data.quiz_id)
    if quiz is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="quiz_not_found",
        )
    if quiz.status is QuizStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_quiz_status",
        )

    psychologist = await db.get(User, data.psychologist_id)
    if (
        psychologist is None
        or psychologist.role is not UserRole.PSYCHOLOGIST
        or not psychologist.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_psychologist",
        )

    profile = await db.get(PsychologistProfile, data.psychologist_id)
    if profile is None or profile.status is not PsychologistStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="psychologist_not_approved",
        )

    existing = await db.scalar(
        select(Recommendation).where(
            Recommendation.quiz_id == quiz.id,
            Recommendation.psychologist_id == data.psychologist_id,
        )
    )

    if existing is not None:
        existing.admin_note = data.admin_note
        if data.rank is not None:
            existing.rank = data.rank
        recommendation = existing
    else:
        rank = data.rank
        if rank is None:
            max_rank = await db.scalar(
                select(func.max(Recommendation.rank)).where(Recommendation.quiz_id == quiz.id)
            )
            rank = (max_rank or 0) + 1

        recommendation = Recommendation(
            quiz_id=quiz.id,
            psychologist_id=data.psychologist_id,
            rank=rank,
            admin_note=data.admin_note,
        )
        db.add(recommendation)

    quiz.status = QuizStatus.RECOMMENDED
    await db.commit()
    await db.refresh(recommendation)
    return recommendation
