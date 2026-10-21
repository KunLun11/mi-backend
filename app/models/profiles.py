"""Профили клиента и психолога, M2M-связи психолога со справочниками."""

from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.dictionaries import Approach, ITContextTag
from app.models.enums import Format, PsychologistStatus, enum_column
from app.models.user import User


class ClientProfile(TimestampMixin, Base):
    """Профиль клиента (1:1 с пользователем)."""

    __tablename__ = "client_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Europe/Moscow",
        nullable=False,
    )
    preferred_format: Mapped[Format] = mapped_column(
        enum_column(Format, "format"),
        default=Format.ONLINE,
        nullable=False,
    )

    user: Mapped[User] = relationship()


class PsychologistProfile(TimestampMixin, Base):
    """Профиль психолога (1:1 с пользователем)."""

    __tablename__ = "psychologist_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    bio: Mapped[str | None] = mapped_column(Text)
    education: Mapped[str | None] = mapped_column(Text)
    years_experience: Mapped[int] = mapped_column(default=0, nullable=False)
    session_price_rub: Mapped[int] = mapped_column(default=0, nullable=False)
    calendar_url: Mapped[str | None] = mapped_column(String(512))
    diploma_file: Mapped[str | None] = mapped_column(String(512))
    supervision_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_verified_it_context: Mapped[bool] = mapped_column(default=False, nullable=False)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PsychologistStatus] = mapped_column(
        enum_column(PsychologistStatus, "psychologist_status"),
        default=PsychologistStatus.DRAFT,
        nullable=False,
    )

    user: Mapped[User] = relationship()
    approaches: Mapped[list[Approach]] = relationship(
        secondary="psychologist_approaches",
        lazy="selectin",
    )
    it_contexts: Mapped[list[ITContextTag]] = relationship(
        secondary="psychologist_it_contexts",
        lazy="selectin",
    )


class PsychologistApproach(Base):
    """Связь психолога с подходом."""

    __tablename__ = "psychologist_approaches"

    psychologist_id: Mapped[UUID] = mapped_column(
        ForeignKey("psychologist_profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    approach_id: Mapped[int] = mapped_column(
        ForeignKey("approaches.id", ondelete="CASCADE"),
        primary_key=True,
    )


class PsychologistITContext(Base):
    """Связь психолога с IT-контекстом."""

    __tablename__ = "psychologist_it_contexts"

    psychologist_id: Mapped[UUID] = mapped_column(
        ForeignKey("psychologist_profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    it_context_id: Mapped[int] = mapped_column(
        ForeignKey("it_context_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )
