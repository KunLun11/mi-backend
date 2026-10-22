"""Бизнес-логика профилей клиента и психолога: чтение, обновление, модерация."""

from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Approach,
    ClientProfile,
    ITContextTag,
    PsychologistProfile,
    PsychologistStatus,
    User,
)
from app.models.enums import Format
from app.schemas.profiles import ClientProfileIn, PsychologistProfileIn


async def get_client_profile(db: AsyncSession, user: User) -> ClientProfile:
    """Вернуть профиль клиента или 404, если он не создан."""
    profile = await db.get(ClientProfile, user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return profile


async def load_client_profiles(
    db: AsyncSession,
    user_ids: Sequence[UUID],
) -> dict[UUID, ClientProfile]:
    """Загрузить профили клиентов одним запросом (индекс — `user_id`)."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}

    result = await db.execute(select(ClientProfile).where(ClientProfile.user_id.in_(ids)))
    return {profile.user_id: profile for profile in result.scalars()}


async def load_psychologist_profiles(
    db: AsyncSession,
    user_ids: Sequence[UUID],
) -> dict[UUID, PsychologistProfile]:
    """Загрузить профили психологов с подходами одним запросом."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}

    result = await db.execute(
        select(PsychologistProfile)
        .where(PsychologistProfile.user_id.in_(ids))
        .options(
            selectinload(PsychologistProfile.approaches),
            selectinload(PsychologistProfile.it_contexts),
        )
    )
    return {profile.user_id: profile for profile in result.scalars()}


async def update_client_profile(
    db: AsyncSession,
    user: User,
    data: ClientProfileIn,
) -> ClientProfile:
    """Обновить переданные поля профиля клиента."""
    profile = await get_client_profile(db, user)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)

    await db.commit()
    await db.refresh(profile)
    return profile


async def _load_psychologist(
    db: AsyncSession,
    user_id: UUID,
) -> PsychologistProfile | None:
    """Загрузить профиль психолога с подходами и IT-контекстами."""
    result = await db.execute(
        select(PsychologistProfile)
        .where(PsychologistProfile.user_id == user_id)
        .options(
            selectinload(PsychologistProfile.approaches),
            selectinload(PsychologistProfile.it_contexts),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_psychologist_profile(db: AsyncSession, user: User) -> PsychologistProfile:
    """Вернуть собственный профиль психолога."""
    profile = await _load_psychologist(db, user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return profile


async def _load_approaches(db: AsyncSession, ids: list[int]) -> list[Approach]:
    """Загрузить подходы по ID, сохранив порядок; неизвестные — 400."""
    if not ids:
        return []

    result = await db.execute(select(Approach).where(Approach.id.in_(ids)))
    found = {item.id: item for item in result.scalars()}
    if any(item_id not in found for item_id in ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown_approach",
        )
    return [found[item_id] for item_id in ids]


async def _load_it_contexts(db: AsyncSession, ids: list[int]) -> list[ITContextTag]:
    """Загрузить IT-контексты по ID, сохранив порядок; неизвестные — 400."""
    if not ids:
        return []

    result = await db.execute(select(ITContextTag).where(ITContextTag.id.in_(ids)))
    found = {item.id: item for item in result.scalars()}
    if any(item_id not in found for item_id in ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown_it_context",
        )
    return [found[item_id] for item_id in ids]


async def update_psychologist_profile(
    db: AsyncSession,
    user: User,
    data: PsychologistProfileIn,
) -> PsychologistProfile:
    """Обновить переданные поля профиля психолога и его справочные связи."""
    profile = await get_psychologist_profile(db, user)
    changes = data.model_dump(exclude_unset=True)

    approach_ids = changes.pop("approach_ids", None)
    it_context_ids = changes.pop("it_context_ids", None)
    formats = changes.pop("formats", None)
    # `first_name` в БД обязателен: явный null не должен его затереть.
    if changes.get("first_name") is None:
        changes.pop("first_name", None)

    for field_name, value in changes.items():
        setattr(profile, field_name, value)

    if formats is not None:
        profile.formats = formats
    if approach_ids is not None:
        profile.approaches = await _load_approaches(db, approach_ids)
    if it_context_ids is not None:
        profile.it_contexts = await _load_it_contexts(db, it_context_ids)

    await db.commit()

    updated = await _load_psychologist(db, user.id)
    if updated is None:  # pragma: no cover - профиль не может исчезнуть при update
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return updated


async def submit_psychologist_profile(
    db: AsyncSession,
    user: User,
) -> PsychologistProfile:
    """Отправить профиль на модерацию: `draft|rejected → pending`."""
    profile = await get_psychologist_profile(db, user)
    if profile.status not in (PsychologistStatus.DRAFT, PsychologistStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid_profile_status",
        )

    profile.status = PsychologistStatus.PENDING
    await db.commit()

    updated = await _load_psychologist(db, user.id)
    if updated is None:  # pragma: no cover - профиль не может исчезнуть при submit
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile_not_found",
        )
    return updated


async def list_psychologists(
    db: AsyncSession,
    *,
    approach: str | None,
    it_context: str | None,
    format_: Format | None,
    page: int,
    page_size: int,
) -> tuple[list[PsychologistProfile], int]:
    """Постраничный список только одобренных психологов с фильтрами."""
    conditions = [PsychologistProfile.status == PsychologistStatus.APPROVED]
    if approach:
        conditions.append(PsychologistProfile.approaches.any(Approach.slug == approach))
    if it_context:
        conditions.append(PsychologistProfile.it_contexts.any(ITContextTag.slug == it_context))
    if format_ is not None:
        conditions.append(PsychologistProfile.formats.contains([format_]))

    result = await db.execute(
        select(PsychologistProfile)
        .where(*conditions)
        .options(
            selectinload(PsychologistProfile.approaches),
            selectinload(PsychologistProfile.it_contexts),
        )
        .order_by(PsychologistProfile.created_at.desc(), PsychologistProfile.user_id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = list(result.scalars().all())

    total = await db.scalar(
        select(func.count()).select_from(PsychologistProfile).where(*conditions)
    )
    return items, int(total or 0)


async def get_public_psychologist(
    db: AsyncSession,
    psychologist_id: UUID,
) -> PsychologistProfile:
    """Публичная карточка одобренного психолога (иначе 404)."""
    result = await db.execute(
        select(PsychologistProfile)
        .where(
            PsychologistProfile.user_id == psychologist_id,
            PsychologistProfile.status == PsychologistStatus.APPROVED,
        )
        .options(
            selectinload(PsychologistProfile.approaches),
            selectinload(PsychologistProfile.it_contexts),
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="psychologist_not_found",
        )
    return profile
