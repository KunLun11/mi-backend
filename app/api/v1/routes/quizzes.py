"""Эндпоинты квиза и ручных рекомендаций."""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ClientUser, SessionDep
from app.schemas.quizzes import QuizIn, QuizOut, RecommendationOut
from app.services import quiz_service

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.post("", response_model=QuizOut, status_code=status.HTTP_201_CREATED)
async def create_quiz(
    payload: QuizIn,
    user: ClientUser,
    db: SessionDep,
) -> QuizOut:
    """Сохранить ответы клиента на квиз."""
    quiz = await quiz_service.create_quiz(db, user, payload)
    return QuizOut.model_validate(quiz)


@router.get("/{quiz_id}", response_model=QuizOut)
async def get_quiz(
    quiz_id: UUID,
    user: ClientUser,
    db: SessionDep,
) -> QuizOut:
    """Прочитать собственный квиз (для polling статуса)."""
    quiz = await quiz_service.get_quiz(db, user, quiz_id)
    return QuizOut.model_validate(quiz)


@router.get("/{quiz_id}/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    quiz_id: UUID,
    user: ClientUser,
    db: SessionDep,
) -> list[RecommendationOut]:
    """Рекомендации куратора по готовому квизу."""
    return await quiz_service.list_recommendations(db, user, quiz_id)
