"""Pydantic-схемы аутентификации (v2)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Format, PsychologistStatus, UserRole


class RegisterRequest(BaseModel):
    """Регистрация по email и паролю."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole

    @field_validator("role")
    @classmethod
    def _forbid_admin(cls, value: UserRole) -> UserRole:
        if value is UserRole.ADMIN:
            raise ValueError("admin role cannot be registered")
        return value


class VerifyEmailRequest(BaseModel):
    """Подтверждение email одноразовым кодом."""

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendCodeRequest(BaseModel):
    """Повторная отправка кода подтверждения."""

    email: EmailStr


class LoginRequest(BaseModel):
    """Вход по email и паролю."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Ротация refresh-токена."""

    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Пара токенов, возвращаемая клиенту."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class OAuthAuthorizeResponse(BaseModel):
    """URL для редиректа пользователя на страницу провайдера."""

    authorize_url: str


class SetRoleRequest(BaseModel):
    """Выбор роли после OAuth-регистрации."""

    role: UserRole

    @field_validator("role")
    @classmethod
    def _forbid_admin(cls, value: UserRole) -> UserRole:
        if value is UserRole.ADMIN:
            raise ValueError("admin role cannot be selected")
        return value


class UserPublic(BaseModel):
    """Публичное представление пользователя."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: UserRole
    email_verified: bool
    role_selected: bool
    created_at: datetime


class ClientProfileOut(BaseModel):
    """Краткое представление профиля клиента."""

    model_config = ConfigDict(from_attributes=True)

    first_name: str | None
    timezone: str
    preferred_format: Format


class PsychologistProfileOut(BaseModel):
    """Краткое представление профиля психолога."""

    model_config = ConfigDict(from_attributes=True)

    first_name: str
    last_name: str | None
    status: PsychologistStatus
    years_experience: int
    session_price_rub: int
    supervision_confirmed: bool
    is_verified_it_context: bool


class MeResponse(UserPublic):
    """Текущий пользователь вместе с его профилем."""

    profile: ClientProfileOut | PsychologistProfileOut | None = None
