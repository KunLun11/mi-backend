"""Эндпоинты терапевтических сессий."""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, PsychologistUser, SessionDep
from app.schemas.sessions import TherapySessionOut
from app.services import therapy_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[TherapySessionOut])
async def list_sessions(
    user: CurrentUser,
    db: SessionDep,
) -> list[TherapySessionOut]:
    """Список своих сессий (клиент или психолог)."""
    return await therapy_service.list_sessions(db, user)


@router.post("/{session_id}/complete", response_model=TherapySessionOut)
async def complete_session(
    session_id: UUID,
    user: PsychologistUser,
    db: SessionDep,
) -> TherapySessionOut:
    """Отметить сессию проведённой и начислить комиссию."""
    return await therapy_service.complete_session(db, user, session_id)


@router.post("/{session_id}/no-show", response_model=TherapySessionOut)
async def mark_no_show(
    session_id: UUID,
    user: PsychologistUser,
    db: SessionDep,
) -> TherapySessionOut:
    """Отметить неявку клиента на сессию."""
    return await therapy_service.mark_no_show(db, user, session_id)
