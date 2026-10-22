"""Pydantic-схемы терапевтических сессий (v2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import TherapyStatus
from app.schemas.profiles import ClientPublic, PsychologistPublic


class TherapySessionOut(BaseModel):
    """Назначенная встреча клиента с психологом."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    client_id: UUID
    psychologist_id: UUID
    scheduled_at: datetime
    duration_minutes: int
    price_rub: int
    status: TherapyStatus
    completed_at: datetime | None
    created_at: datetime
    psychologist: PsychologistPublic | None = None
    client: ClientPublic | None = None
