"""Pydantic-схемы заявок на сессию (v2)."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RequestStatus
from app.schemas.profiles import ClientPublic, PsychologistPublic


class SessionRequestIn(BaseModel):
    """Заявка клиента на сессию по рекомендации."""

    recommendation_id: UUID
    message: str | None = Field(default=None, max_length=2000)
    preferred_time: datetime | None = None

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("preferred_time")
    @classmethod
    def _ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SessionRequestAcceptIn(BaseModel):
    """Подтверждение заявки психологом: время и цена встречи."""

    scheduled_at: datetime
    price_rub: int = Field(ge=0, le=1_000_000)

    @field_validator("scheduled_at")
    @classmethod
    def _ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SessionRequestOut(BaseModel):
    """Заявка клиента психологу."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    quiz_id: UUID | None
    recommendation_id: UUID | None
    client_id: UUID
    psychologist_id: UUID
    message: str | None
    preferred_time: datetime | None
    status: RequestStatus
    created_at: datetime
    psychologist: PsychologistPublic | None = None
    client: ClientPublic | None = None
