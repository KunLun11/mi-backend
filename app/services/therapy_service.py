"""Бизнес-логика терапевтических сессий."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ClientProfile,
    PsychologistProfile,
    PsychologistStatus,
    RequestStatus,
    SessionRequest,
    TherapySession,
    TherapyStatus,
    User,
    UserRole,
)
from app.schemas.profiles import ClientPublic, PsychologistPublic
from app.schemas.sessions import TherapySessionOut
from app.services import commission_service
from app.services.profile_service import load_client_profiles, load_psychologist_profiles


def session_out(
    session: TherapySession,
    psychologist: PsychologistProfile | None,
    client: ClientProfile | None,
) -> TherapySessionOut:
    """Собрать ответ по сессии с карточками участников."""
    return TherapySessionOut(
        id=session.id,
        request_id=session.request_id,
        client_id=session.client_id,
        psychologist_id=session.psychologist_id,
        scheduled_at=session.scheduled_at,
        duration_minutes=session.duration_minutes,
        price_rub=session.price_rub,
        status=session.status,
        completed_at=session.completed_at,
        created_at=session.created_at,
        psychologist=(
            PsychologistPublic.model_validate(psychologist) if psychologist is not None else None
        ),
        client=ClientPublic.model_validate(client) if client is not None else None,
    )


async def list_sessions(db: AsyncSession, user: User) -> list[TherapySessionOut]:
    """Сессии пользователя: клиент — свои, психолог — свои встречи."""
    if user.role is UserRole.CLIENT:
        condition = TherapySession.client_id == user.id
    elif user.role is UserRole.PSYCHOLOGIST:
        profile = await db.get(PsychologistProfile, user.id)
        if profile is None or profile.status is not PsychologistStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="psychologist_not_approved",
            )
        condition = TherapySession.psychologist_id == user.id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden_role",
        )

    result = await db.execute(
        select(TherapySession)
        .where(condition)
        .order_by(TherapySession.scheduled_at.desc(), TherapySession.id)
    )
    sessions = list(result.scalars().all())

    profiles = await load_psychologist_profiles(
        db,
        [item.psychologist_id for item in sessions],
    )
    clients = await load_client_profiles(db, [item.client_id for item in sessions])

    return [
        session_out(
            item,
            profiles.get(item.psychologist_id),
            clients.get(item.client_id),
        )
        for item in sessions
    ]


async def _load_owned_session(
    db: AsyncSession,
    user: User,
    session_id: UUID,
) -> TherapySession:
    """Загрузить сессию, принадлежащую психологу; иначе 404."""
    profile = await db.get(PsychologistProfile, user.id)
    if profile is None or profile.status is not PsychologistStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="psychologist_not_approved",
        )

    session = await db.get(TherapySession, session_id)
    if session is None or session.psychologist_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session_not_found",
        )
    return session


async def _session_response(db: AsyncSession, session: TherapySession) -> TherapySessionOut:
    """Собрать ответ по одной сессии с карточками участников."""
    profiles = await load_psychologist_profiles(db, [session.psychologist_id])
    clients = await load_client_profiles(db, [session.client_id])
    return session_out(
        session,
        profiles.get(session.psychologist_id),
        clients.get(session.client_id),
    )


async def complete_session(
    db: AsyncSession,
    user: User,
    session_id: UUID,
) -> TherapySessionOut:
    """Отметить сессию проведённой и начислить комиссию сервиса."""
    session = await _load_owned_session(db, user, session_id)
    if session.status is not TherapyStatus.SCHEDULED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_session_status",
        )

    session.status = TherapyStatus.COMPLETED
    session.completed_at = datetime.now(UTC)

    request = await db.get(SessionRequest, session.request_id)
    if request is not None:
        request.status = RequestStatus.COMPLETED

    await commission_service.create_commission(db, session)
    await db.commit()
    await db.refresh(session)
    return await _session_response(db, session)


async def mark_no_show(
    db: AsyncSession,
    user: User,
    session_id: UUID,
) -> TherapySessionOut:
    """Отметить неявку клиента на сессию."""
    session = await _load_owned_session(db, user, session_id)
    if session.status is not TherapyStatus.SCHEDULED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_session_status",
        )

    session.status = TherapyStatus.NO_SHOW
    await db.commit()
    await db.refresh(session)
    return await _session_response(db, session)
