"""Pydantic-схемы профилей клиента и психолога (v2)."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Format, PsychologistStatus

_TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$")
_NAME_MAX = 100


class DictionaryItem(BaseModel):
    """Элемент справочника (подход, IT-контекст, запрос)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class ClientProfileIn(BaseModel):
    """Обновление профиля клиента (передаются только изменяемые поля)."""

    first_name: str | None = Field(default=None, max_length=_NAME_MAX)
    timezone: str = Field(default="Europe/Moscow", max_length=64)
    preferred_format: Format = Format.ONLINE

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        value = value.strip()
        if not _TIMEZONE_RE.fullmatch(value):
            raise ValueError("invalid_timezone")
        return value


class ClientProfileOut(BaseModel):
    """Полное представление профиля клиента."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    first_name: str | None
    timezone: str
    preferred_format: Format
    created_at: datetime
    updated_at: datetime


class ClientPublic(BaseModel):
    """Короткая карточка клиента для заявок и сессий психолога."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    first_name: str | None
    timezone: str


class PsychologistProfileIn(BaseModel):
    """Обновление профиля психолога (передаются только изменяемые поля).

    Управляемые модератором поля (`status`, `supervision_confirmed`,
    `is_verified_it_context`, `verification_notes`) недоступны для изменения.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    last_name: str | None = Field(default=None, max_length=_NAME_MAX)
    photo_url: str | None = Field(default=None, max_length=512)
    bio: str | None = Field(default=None, max_length=5000)
    education: str | None = Field(default=None, max_length=5000)
    years_experience: int = Field(default=0, ge=0, le=80)
    session_price_rub: int = Field(default=0, ge=0, le=1_000_000)
    calendar_url: str | None = Field(default=None, max_length=512)
    diploma_file: str | None = Field(default=None, max_length=512)
    formats: list[Format] | None = Field(default=None, min_length=1)
    approach_ids: list[int] | None = None
    it_context_ids: list[int] | None = None

    @field_validator("formats")
    @classmethod
    def _dedupe_formats(cls, value: list[Format] | None) -> list[Format] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @field_validator("approach_ids", "it_context_ids")
    @classmethod
    def _dedupe_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(item_id <= 0 for item_id in value):
            raise ValueError("invalid_dictionary_id")
        return list(dict.fromkeys(value))


class PsychologistProfileOut(BaseModel):
    """Полное представление профиля психолога (для владельца)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    first_name: str
    last_name: str | None
    photo_url: str | None
    bio: str | None
    education: str | None
    years_experience: int
    session_price_rub: int
    calendar_url: str | None
    diploma_file: str | None
    supervision_confirmed: bool
    is_verified_it_context: bool
    verification_notes: str | None
    formats: list[Format]
    status: PsychologistStatus
    approaches: list[DictionaryItem]
    it_contexts: list[DictionaryItem]
    created_at: datetime
    updated_at: datetime


class PsychologistPublic(BaseModel):
    """Публичная карточка психолога (только поля для клиента)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    first_name: str
    last_name: str | None
    photo_url: str | None
    bio: str | None
    education: str | None
    years_experience: int
    session_price_rub: int
    calendar_url: str | None
    formats: list[Format]
    is_verified_it_context: bool
    approaches: list[DictionaryItem]
    it_contexts: list[DictionaryItem]


class PsychologistListResponse(BaseModel):
    """Страница списка психологов."""

    items: list[PsychologistPublic]
    total: int
