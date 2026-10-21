"""ORM-модели.

Импорт пакета регистрирует все таблицы в `Base.metadata` — это использует
Alembic при автогенерации миграций.
"""

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.dictionaries import Approach, Concern, ITContextTag
from app.models.enums import (
    CommissionRateType,
    CommissionStatus,
    Format,
    ITRole,
    OAuthProvider,
    PsychologistStatus,
    QuizStatus,
    RequestStatus,
    TherapyStatus,
    UserRole,
)
from app.models.profiles import (
    ClientProfile,
    PsychologistApproach,
    PsychologistITContext,
    PsychologistProfile,
)
from app.models.quiz import QuizResponse, Recommendation
from app.models.therapy import Commission, SessionRequest, TherapySession
from app.models.user import EmailVerificationCode, OAuthAccount, User, UserSession

__all__ = [
    "Approach",
    "Base",
    "ClientProfile",
    "Commission",
    "CommissionRateType",
    "CommissionStatus",
    "Concern",
    "EmailVerificationCode",
    "Format",
    "ITContextTag",
    "ITRole",
    "OAuthAccount",
    "OAuthProvider",
    "PsychologistApproach",
    "PsychologistITContext",
    "PsychologistProfile",
    "PsychologistStatus",
    "QuizResponse",
    "QuizStatus",
    "Recommendation",
    "RequestStatus",
    "SessionRequest",
    "TherapySession",
    "TherapyStatus",
    "TimestampMixin",
    "User",
    "UserRole",
    "UserSession",
    "UUIDMixin",
]
