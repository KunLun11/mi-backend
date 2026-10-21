"""Перечисления домена.

Все Enum хранятся как `VARCHAR` (`native_enum=False`), без нативных PG ENUM.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum


def enum_column(enum_cls: type[StrEnum], name: str) -> Any:
    """SAEnum, сохраняющий значения членов (`client`), а не их имена (`CLIENT`)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


class UserRole(StrEnum):
    """Роль пользователя."""

    CLIENT = "client"
    PSYCHOLOGIST = "psychologist"
    ADMIN = "admin"


class OAuthProvider(StrEnum):
    """Поддерживаемые OAuth-провайдеры."""

    YANDEX = "yandex"
    GOOGLE = "google"
    GITHUB = "github"


class Format(StrEnum):
    """Формат консультаций."""

    ONLINE = "online"
    OFFLINE = "offline"
    BOTH = "both"


class PsychologistStatus(StrEnum):
    """Статус модерации профиля психолога."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ITRole(StrEnum):
    """Роль клиента в IT."""

    DEVELOPER = "developer"
    QA = "qa"
    PM = "pm"
    DEVOPS = "devops"
    DESIGNER = "designer"
    MANAGER = "manager"
    OTHER = "other"


class QuizStatus(StrEnum):
    """Статус квиза."""

    SUBMITTED = "submitted"
    PROCESSING = "processing"
    RECOMMENDED = "recommended"
    CLOSED = "closed"


class RequestStatus(StrEnum):
    """Статус заявки на сессию."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class TherapyStatus(StrEnum):
    """Статус терапевтической сессии."""

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"


class CommissionRateType(StrEnum):
    """Тип ставки комиссии."""

    FIXED = "fixed"
    PERCENT = "percent"


class CommissionStatus(StrEnum):
    """Статус комиссии."""

    PENDING = "pending"
    INVOICED = "invoiced"
    PAID = "paid"
