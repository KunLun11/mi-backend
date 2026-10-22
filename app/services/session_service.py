"""Бизнес-логика заявок на сессию."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ClientProfile,
    PsychologistProfile,
    PsychologistStatus,
    QuizResponse,
    QuizStatus,
    Recommendation,
    RequestStatus,
    SessionRequest,
    TherapySession,
    TherapyStatus,
    User,
    UserRole,
)
from app.schemas.profiles import ClientPublic, PsychologistPublic
from app.schemas.session_requests import (
    SessionRequestAcceptIn,
    SessionRequestIn,
    SessionRequestOut,
)
from app.schemas.sessions import TherapySessionOut
from app.services import therapy_service
from app.services.profile_service import load_client_profiles, load_psychologist_profiles


def _request_out(
    request: SessionRequest,
    psychologist: PsychologistProfile | None,
    client: ClientProfile | None,
) -> SessionRequestOut:
    """Собрать ответ по заявке с профилями участников."""
    return SessionRequestOut(
        id=request.id,
        quiz_id=request.quiz_id,
        recommendation_id=request.recommendation_id,
        client_id=request.client_id,
        psychologist_id=request.psychologist_id,
        message=request.message,
        preferred_time=request.preferred_time,
        status=request.status,
        created_at=request.created_at,
        psychologist=(
            PsychologistPublic.model_validate(psychologist) if psychologist is not None else None
        ),
        client=ClientPublic.model_validate(client) if client is not None else None,
    )


async def _ensure_psychologist_approved(db: AsyncSession, user: User) -> None:
    """Психолог без статуса `approved` не может работать с заявками."""
    profile = await db.get(PsychologistProfile, user.id)
    if profile is None or profile.status is not PsychologistStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="psychologist_not_approved",
        )


async def create_session_request(
    db: AsyncSession,
    user: User,
    data: SessionRequestIn,
) -> SessionRequestOut:
    """Создать заявку клиента по рекомендации из `recommended` квиза."""
    recommendation = await db.get(Recommendation, data.recommendation_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="recommendation_not_found",
        )

    quiz = await db.get(QuizResponse, recommendation.quiz_id)
    if quiz is None or quiz.client_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="recommendation_not_found",
        )

    if quiz.status is not QuizStatus.RECOMMENDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="quiz_not_ready",
        )

    profile = await db.get(PsychologistProfile, recommendation.psychologist_id)
    if profile is None or profile.status is not PsychologistStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="psychologist_not_approved",
        )

    existing = await db.scalar(
        select(SessionRequest).where(
            SessionRequest.recommendation_id == recommendation.id,
            SessionRequest.client_id == user.id,
            SessionRequest.status.in_((RequestStatus.PENDING, RequestStatus.ACCEPTED)),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="request_exists",
        )

    request = SessionRequest(
        quiz_id=quiz.id,
        recommendation_id=recommendation.id,
        client_id=user.id,
        psychologist_id=recommendation.psychologist_id,
        message=data.message,
        preferred_time=data.preferred_time,
        status=RequestStatus.PENDING,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    profiles = await load_psychologist_profiles(db, [request.psychologist_id])
    clients = await load_client_profiles(db, [request.client_id])
    return _request_out(
        request,
        profiles.get(request.psychologist_id),
        clients.get(request.client_id),
    )


async def list_session_requests(
    db: AsyncSession,
    user: User,
) -> list[SessionRequestOut]:
    """Заявки пользователя: клиент — свои, психолог — входящие."""
    if user.role is UserRole.CLIENT:
        condition = SessionRequest.client_id == user.id
    elif user.role is UserRole.PSYCHOLOGIST:
        await _ensure_psychologist_approved(db, user)
        condition = SessionRequest.psychologist_id == user.id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden_role",
        )

    result = await db.execute(
        select(SessionRequest)
        .where(condition)
        .order_by(SessionRequest.created_at.desc(), SessionRequest.id)
    )
    requests = list(result.scalars().all())

    profiles = await load_psychologist_profiles(
        db,
        [item.psychologist_id for item in requests],
    )
    clients = await load_client_profiles(db, [item.client_id for item in requests])

    return [
        _request_out(
            item,
            profiles.get(item.psychologist_id),
            clients.get(item.client_id),
        )
        for item in requests
    ]


async def cancel_session_request(
    db: AsyncSession,
    user: User,
    request_id: UUID,
) -> SessionRequestOut:
    """Отменить заявку в статусе `pending|accepted` (клиент или психолог)."""
    request = await db.get(SessionRequest, request_id)
    if request is None or user.id not in (request.client_id, request.psychologist_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="request_not_found",
        )

    if request.status not in (RequestStatus.PENDING, RequestStatus.ACCEPTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_request_status",
        )

    request.status = RequestStatus.CANCELLED

    session = await db.scalar(select(TherapySession).where(TherapySession.request_id == request.id))
    if session is not None and session.status is TherapyStatus.SCHEDULED:
        session.status = TherapyStatus.CANCELLED

    await db.commit()
    await db.refresh(request)

    profiles = await load_psychologist_profiles(db, [request.psychologist_id])
    clients = await load_client_profiles(db, [request.client_id])
    return _request_out(
        request,
        profiles.get(request.psychologist_id),
        clients.get(request.client_id),
    )


async def _load_psychologist_request(
    db: AsyncSession,
    user: User,
    request_id: UUID,
) -> SessionRequest:
    """Загрузить входящую заявку психолога; проверяет статус модерации."""
    await _ensure_psychologist_approved(db, user)

    request = await db.get(SessionRequest, request_id)
    if request is None or request.psychologist_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="request_not_found",
        )
    return request


async def accept_session_request(
    db: AsyncSession,
    user: User,
    request_id: UUID,
    data: SessionRequestAcceptIn,
) -> TherapySessionOut:
    """Принять заявку: `pending → accepted` и создать сессию."""
    request = await _load_psychologist_request(db, user, request_id)
    if request.status is not RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_request_status",
        )

    session = TherapySession(
        request_id=request.id,
        client_id=request.client_id,
        psychologist_id=user.id,
        scheduled_at=data.scheduled_at,
        price_rub=data.price_rub,
        status=TherapyStatus.SCHEDULED,
    )
    request.status = RequestStatus.ACCEPTED
    db.add(session)

    await db.commit()
    await db.refresh(session)

    profiles = await load_psychologist_profiles(db, [session.psychologist_id])
    clients = await load_client_profiles(db, [session.client_id])
    return therapy_service.session_out(
        session,
        profiles.get(session.psychologist_id),
        clients.get(session.client_id),
    )


async def decline_session_request(
    db: AsyncSession,
    user: User,
    request_id: UUID,
) -> SessionRequestOut:
    """Отклонить заявку: `pending → declined`."""
    request = await _load_psychologist_request(db, user, request_id)
    if request.status is not RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_request_status",
        )

    request.status = RequestStatus.DECLINED
    await db.commit()
    await db.refresh(request)

    profiles = await load_psychologist_profiles(db, [request.psychologist_id])
    clients = await load_client_profiles(db, [request.client_id])
    return _request_out(
        request,
        profiles.get(request.psychologist_id),
        clients.get(request.client_id),
    )
