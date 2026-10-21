"""Заявки на сессию, терапевтические сессии и комиссии."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import (
    CommissionRateType,
    CommissionStatus,
    RequestStatus,
    TherapyStatus,
    enum_column,
)
from app.models.quiz import QuizResponse, Recommendation
from app.models.user import User


class SessionRequest(UUIDMixin, TimestampMixin, Base):
    """Заявка клиента психологу на сессию."""

    __tablename__ = "session_requests"

    quiz_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quiz_responses.id", ondelete="SET NULL"),
        index=True,
    )
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        index=True,
    )
    client_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    psychologist_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message: Mapped[str | None] = mapped_column(Text)
    preferred_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RequestStatus] = mapped_column(
        enum_column(RequestStatus, "request_status"),
        default=RequestStatus.PENDING,
        nullable=False,
    )

    quiz: Mapped[QuizResponse | None] = relationship()
    recommendation: Mapped[Recommendation | None] = relationship()
    client: Mapped[User] = relationship(foreign_keys=[client_id])
    psychologist: Mapped[User] = relationship(foreign_keys=[psychologist_id])


class TherapySession(UUIDMixin, Base):
    """Назначенная терапевтическая сессия (1:1 с принятой заявкой)."""

    __tablename__ = "therapy_sessions"

    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("session_requests.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    client_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    psychologist_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(default=50, nullable=False)
    price_rub: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[TherapyStatus] = mapped_column(
        enum_column(TherapyStatus, "therapy_status"),
        default=TherapyStatus.SCHEDULED,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    request: Mapped[SessionRequest] = relationship()
    client: Mapped[User] = relationship(foreign_keys=[client_id])
    psychologist: Mapped[User] = relationship(foreign_keys=[psychologist_id])
    commission: Mapped["Commission | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class Commission(UUIDMixin, Base):
    """Комиссия сервиса по завершённой сессии."""

    __tablename__ = "commissions"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("therapy_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    amount_rub: Mapped[int] = mapped_column(nullable=False)
    rate_type: Mapped[CommissionRateType] = mapped_column(
        enum_column(CommissionRateType, "commission_rate_type"),
        nullable=False,
    )
    rate_value: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    status: Mapped[CommissionStatus] = mapped_column(
        enum_column(CommissionStatus, "commission_status"),
        default=CommissionStatus.PENDING,
        nullable=False,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[TherapySession] = relationship(back_populates="commission")
