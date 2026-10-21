"""Эндпоинты профиля психолога и публичного каталога."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, PsychologistUser, SessionDep
from app.models.enums import Format
from app.schemas.profiles import (
    PsychologistListResponse,
    PsychologistProfileIn,
    PsychologistProfileOut,
    PsychologistPublic,
)
from app.services import profile_service

router = APIRouter(prefix="/psychologists", tags=["psychologists"])


@router.get("/me", response_model=PsychologistProfileOut)
async def get_my_profile(user: PsychologistUser, db: SessionDep) -> PsychologistProfileOut:
    """Прочитать собственный профиль психолога."""
    profile = await profile_service.get_psychologist_profile(db, user)
    return PsychologistProfileOut.model_validate(profile)


@router.put("/me", response_model=PsychologistProfileOut)
async def update_my_profile(
    payload: PsychologistProfileIn,
    user: PsychologistUser,
    db: SessionDep,
) -> PsychologistProfileOut:
    """Обновить собственный профиль психолога."""
    profile = await profile_service.update_psychologist_profile(db, user, payload)
    return PsychologistProfileOut.model_validate(profile)


@router.post("/me/submit", response_model=PsychologistProfileOut)
async def submit_my_profile(
    user: PsychologistUser,
    db: SessionDep,
) -> PsychologistProfileOut:
    """Отправить профиль на модерацию (`draft|rejected → pending`)."""
    profile = await profile_service.submit_psychologist_profile(db, user)
    return PsychologistProfileOut.model_validate(profile)


@router.get("", response_model=PsychologistListResponse)
async def list_psychologists(
    _user: CurrentUser,
    db: SessionDep,
    approach: Annotated[str | None, Query(max_length=100)] = None,
    it_context: Annotated[str | None, Query(max_length=100)] = None,
    format_: Annotated[Format | None, Query(alias="format")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PsychologistListResponse:
    """Каталог одобренных психологов с фильтрами и пагинацией."""
    items, total = await profile_service.list_psychologists(
        db,
        approach=approach,
        it_context=it_context,
        format_=format_,
        page=page,
        page_size=page_size,
    )
    return PsychologistListResponse(
        items=[PsychologistPublic.model_validate(item) for item in items],
        total=total,
    )


@router.get("/{psychologist_id}", response_model=PsychologistPublic)
async def get_psychologist(
    psychologist_id: UUID,
    _user: CurrentUser,
    db: SessionDep,
) -> PsychologistPublic:
    """Публичная карточка одобренного психолога."""
    profile = await profile_service.get_public_psychologist(db, psychologist_id)
    return PsychologistPublic.model_validate(profile)
