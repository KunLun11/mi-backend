"""Квиз клиента и ручные рекомендации психологов."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.dictionaries import Concern
from app.models.enums import Format, ITRole, QuizStatus, enum_column
from app.models.user import User


class QuizResponse(UUIDMixin, TimestampMixin, Base):
    """Ответы клиента на квиз подбора."""

    __tablename__ = "quiz_responses"

    client_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_in_it: Mapped[ITRole] = mapped_column(
        enum_column(ITRole, "it_role"),
        nullable=False,
    )
    primary_concern_id: Mapped[int] = mapped_column(
        ForeignKey("concerns.id"),
        nullable=False,
        index=True,
    )
    preferred_format: Mapped[Format] = mapped_column(
        enum_column(Format, "format"),
        nullable=False,
    )
    preferred_price_max: Mapped[int | None] = mapped_column()
    free_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[QuizStatus] = mapped_column(
        enum_column(QuizStatus, "quiz_status"),
        default=QuizStatus.SUBMITTED,
        nullable=False,
    )

    client: Mapped[User] = relationship(foreign_keys=[client_id])
    primary_concern: Mapped[Concern] = relationship()
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Recommendation(UUIDMixin, Base):
    """Рекомендация психолога клиенту (создаётся вручную админом)."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "quiz_id",
            "psychologist_id",
            name="uq_recommendations_quiz_id_psychologist_id",
        ),
    )

    quiz_id: Mapped[UUID] = mapped_column(
        ForeignKey("quiz_responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    psychologist_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(default=1, nullable=False)
    admin_note: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    quiz: Mapped[QuizResponse] = relationship(back_populates="recommendations")
    psychologist: Mapped[User] = relationship(foreign_keys=[psychologist_id])
    recommender: Mapped[User | None] = relationship(foreign_keys=[recommended_by])
