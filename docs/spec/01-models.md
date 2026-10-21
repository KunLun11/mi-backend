# 01 — Модели данных (SQLAlchemy 2.0)

Базовые миксины в `models/base.py`:
- `Base(DeclarativeBase)`.
- `UUIDMixin`: `id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)`.
- `TimestampMixin`: `created_at`, `updated_at` (`server_default=func.now()`,
  `onupdate=func.now()`).

Все Enum — `StrEnum` + `SAEnum(..., native_enum=False, length=32)`.

## User (`users`)
- `id: UUID` PK, `email: str(255)` unique index, `password_hash: str | None`,
  `role: UserRole` (`client|psychologist|admin`), `email_verified: bool=False`,
  `role_selected: bool=False`, `is_active: bool=True`, timestamps.
- 1:N: `oauth_accounts`, `sessions`, `email_codes` (cascade delete).

## OAuthAccount (`oauth_accounts`)
- `id: UUID` PK, `user_id: UUID` FK (CASCADE), `provider: OAuthProvider`
  (`yandex|google|github`), `provider_user_id: str(255)`,
  `provider_email: str | None`, `access_token: str | None`,
  `refresh_token: str | None`, `expires_at: datetime | None`, timestamps.
- UniqueConstraint(`provider`, `provider_user_id`).

## EmailVerificationCode (`email_verification_codes`)
- `id: UUID` PK, `user_id: UUID` FK (CASCADE, index), `code_hash: str(255)`,
  `expires_at: datetime`, `consumed_at: datetime | None`, `created_at`.

## UserSession (`user_sessions`)
- `id: UUID` PK, `user_id: UUID` FK (CASCADE, index), `family_id: UUID` (index),
  `refresh_token_hash: str(255)`, `rotation_counter: int=0`,
  `user_agent: str | None`, `ip_address: str | None`, `created_at`,
  `last_used_at`, `expires_at: datetime`, `revoked_at: datetime | None`.

## Справочники
`Approach`, `ITContextTag`, `Concern`: `id: int` PK, `slug: str` unique, `name: str`.

## ClientProfile (`client_profiles`)
- `user_id: UUID` PK FK (CASCADE), `first_name: str(100) | None`,
  `timezone: str(64)="Europe/Moscow"`, `preferred_format: Format`
  (`online|offline|both`), timestamps.

## PsychologistProfile (`psychologist_profiles`)
- `user_id: UUID` PK FK (CASCADE), `first_name: str(100)`,
  `last_name: str(100) | None`, `photo_url: str | None`, `bio: Text | None`,
  `education: Text | None`, `years_experience: int=0`, `session_price_rub: int`,
  `calendar_url: str | None`, `diploma_file: str | None`,
  `supervision_confirmed: bool=False`, `is_verified_it_context: bool=False`,
  `verification_notes: Text | None`,
  `status: PsychologistStatus` (`draft|pending|approved|rejected`, default `draft`),
  timestamps.
- M2M: `approaches` (через `psychologist_approaches`),
  `it_contexts` (через `psychologist_it_contexts`).

## QuizResponse (`quiz_responses`)
- `id: UUID` PK, `client_id: UUID` FK, `role_in_it: ITRole`
  (`developer|qa|pm|devops|designer|manager|other`),
  `primary_concern_id: int` FK, `preferred_format: Format`,
  `preferred_price_max: int | None`, `free_text: Text | None`,
  `status: QuizStatus` (`submitted|processing|recommended|closed`), timestamps.

## Recommendation (`recommendations`)
- `id: UUID` PK, `quiz_id: UUID` FK (CASCADE), `psychologist_id: UUID` FK,
  `rank: int=1`, `admin_note: Text` (обязательно), `recommended_by: UUID | None`
  FK, `created_at`.
- UniqueConstraint(`quiz_id`, `psychologist_id`).

## SessionRequest (`session_requests`)
- `id: UUID` PK, `quiz_id: UUID | None` FK, `recommendation_id: UUID | None` FK,
  `client_id: UUID` FK, `psychologist_id: UUID` FK, `message: Text | None`,
  `preferred_time: datetime | None`,
  `status: RequestStatus` (`pending|accepted|declined|cancelled|completed`),
  timestamps.

## TherapySession (`therapy_sessions`)
- `id: UUID` PK, `request_id: UUID` unique FK (CASCADE), `client_id: UUID`,
  `psychologist_id: UUID`, `scheduled_at: datetime`, `duration_minutes: int=50`,
  `price_rub: int`, `status: TherapyStatus`
  (`scheduled|completed|no_show|cancelled`), `completed_at: datetime | None`,
  `created_at`.

## Commission (`commissions`)
- `id: UUID` PK, `session_id: UUID` unique FK (CASCADE), `amount_rub: int`,
  `rate_type: CommissionRateType` (`fixed|percent`),
  `rate_value: Decimal(6,2)`,
  `status: CommissionStatus` (`pending|invoiced|paid`),
  `paid_at: datetime | None`, `created_at`.