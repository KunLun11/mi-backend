"""Pydantic-схемы квиза и ручных рекомендаций (v2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Format, ITRole, QuizStatus
from app.schemas.profiles import PsychologistPublic


class QuizIn(BaseModel):
    """Ответы клиента на квиз подбора."""

    role_in_it: ITRole
    primary_concern_id: int = Field(gt=0)
    preferred_format: Format
    preferred_price_max: int | None = Field(default=None, ge=0, le=1_000_000)
    free_text: str | None = Field(default=None, max_length=5000)

    @field_validator("free_text")
    @classmethod
    def _strip_free_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class QuizOut(BaseModel):
    """Квиз клиента."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    role_in_it: ITRole
    primary_concern_id: int
    preferred_format: Format
    preferred_price_max: int | None
    free_text: str | None
    status: QuizStatus
    created_at: datetime


class RecommendationOut(BaseModel):
    """Рекомендация психолога с обоснованием куратора."""

    id: UUID
    quiz_id: UUID
    rank: int
    admin_note: str
    psychologist: PsychologistPublic


class RecommendationCreate(BaseModel):
    """Данные для CLI-скрипта рекомендаций."""

    quiz_id: UUID
    psychologist_id: UUID
    admin_note: str = Field(min_length=1, max_length=5000)
    rank: int | None = Field(default=None, ge=1)
