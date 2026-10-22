"""Эндпоинты заявок на сессию."""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ClientUser, CurrentUser, PsychologistUser, SessionDep
from app.schemas.session_requests import (
    SessionRequestAcceptIn,
    SessionRequestIn,
    SessionRequestOut,
)
from app.schemas.sessions import TherapySessionOut
from app.services import session_service

router = APIRouter(prefix="/session-requests", tags=["session-requests"])


@router.post("", response_model=SessionRequestOut, status_code=status.HTTP_201_CREATED)
async def create_session_request(
    payload: SessionRequestIn,
    user: ClientUser,
    db: SessionDep,
) -> SessionRequestOut:
    """Создать заявку клиента по рекомендации куратора."""
    return await session_service.create_session_request(db, user, payload)


@router.get("", response_model=list[SessionRequestOut])
async def list_session_requests(
    user: CurrentUser,
    db: SessionDep,
) -> list[SessionRequestOut]:
    """Заявки пользователя: клиент — свои, психолог — входящие."""
    return await session_service.list_session_requests(db, user)


@router.post("/{request_id}/accept", response_model=TherapySessionOut)
async def accept_session_request(
    request_id: UUID,
    payload: SessionRequestAcceptIn,
    user: PsychologistUser,
    db: SessionDep,
) -> TherapySessionOut:
    """Принять заявку и назначить встречу (`pending → accepted`)."""
    return await session_service.accept_session_request(db, user, request_id, payload)


@router.post("/{request_id}/decline", response_model=SessionRequestOut)
async def decline_session_request(
    request_id: UUID,
    user: PsychologistUser,
    db: SessionDep,
) -> SessionRequestOut:
    """Отклонить заявку (`pending → declined`)."""
    return await session_service.decline_session_request(db, user, request_id)


@router.post("/{request_id}/cancel", response_model=SessionRequestOut)
async def cancel_session_request(
    request_id: UUID,
    user: CurrentUser,
    db: SessionDep,
) -> SessionRequestOut:
    """Отменить заявку в статусе `pending|accepted`."""
    return await session_service.cancel_session_request(db, user, request_id)
