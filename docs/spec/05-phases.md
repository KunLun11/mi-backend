# 05 — Фазы реализации

Работай по одной фазе. После каждой — стоп, покажи результат,
дождись подтверждения.

## Фаза 0 — каркас (0.5 дня)
- `docker-compose.yml` (postgres, redis, mailhog), `pyproject.toml`,
  `Settings`, `database.py` (async engine + session), `main.py` с `/health`,
  Alembic init.
- **Acceptance:** `docker compose up` поднимает стек, `/health` → `{"status":"ok"}`.

## Фаза 1 — модели и миграции (1 день)
- Все модели из `01-models.md`, `models/__init__.py` с экспортом,
  первая миграция `alembic revision --autogenerate`.
- **Acceptance:** `alembic upgrade head` создаёт таблицы; в моделях нет
  `Column(...)`; все Enum — `native_enum=False`.

## Фаза 2 — auth: email + пароль (2 дня)
- `security.py` (argon2, коды), `email_service` (aiosmtplib + Jinja2),
  `token_service` (create/refresh/revoke), `auth_service`.
- Эндпоинты: register, verify-email, resend-code, login, refresh, logout, me.
- Rate limiting через Redis.
- **Acceptance:** e2e-тест: регистрация → письмо в Mailhog → verify → login →
  refresh → logout → повторный refresh 401. Reuse detection: два refresh
  со старым → family отозвана.

## Фаза 3 — OAuth (1.5 дня)
- `oauth_service` на authlib: Yandex (обязательно), Google, GitHub (если время).
- `authorize`, `callback`, Redis-state, привязка аккаунтов, `set-role`.
- **Acceptance:** тест с моком провайдера (`respx`): новый пользователь,
  существующий OAuthAccount, привязка к существующему email.

## Фаза 4 — профили и справочники (1 день)
- `ClientProfile`, `PsychologistProfile`, M2M, `submit` на модерацию.
- `scripts/seed_dicts.py` — 5 подходов + 12 IT-контекстов + 8 concerns
  (см. `06-seed.md`).
- **Acceptance:** клиент и психолог читают/обновляют профиль;
  `GET /psychologists` — только `approved`.

## Фаза 5 — квиз и ручные рекомендации (1.5 дня)
- `quiz_service`, эндпоинты квиза.
- `scripts/recommend.py` — CLI для создания `Recommendation`.
- **Acceptance:** клиент создаёт квиз → CLI добавляет 2 рекомендации →
  `status=recommended` → клиент видит рекомендации с `admin_note`.

## Фаза 6 — заявки, сессии, комиссии (2 дня)
- `session_service`, `commission_service`, эндпоинты из `03-api.md`.
- **Acceptance:** e2e: заявка → accept → сессия `scheduled` →
  complete → `Commission` `pending`.

## Фаза 7 — фронтенд (3–4 дня)
- Экран логина/регистрации, verify-email, OAuth-кнопки.
- Квиз (5 шагов), рекомендации.
- Кабинеты клиента и психолога.
- Axios interceptor (refresh на 401, logout при неудаче).
- **Acceptance:** полный happy-path в браузере.

## Фаза 8 — тесты и стабилизация (1.5 дня)
- `pytest-asyncio` + `httpx.AsyncClient`, тестовая БД.
- Покрыть auth, quiz→recommendation, request→session→commission.
- **Acceptance:** `pytest` зелёный, `ruff check` и `mypy --strict` чистые.

## CLI-скрипты (в `backend/scripts/`)
- `make_admin.py <email>` — повысить роль.
- `recommend.py <quiz_id> <psychologist_id> "<admin_note>" [rank]` —
  создать `Recommendation` и обновить статус квиза.
- `moderate_psychologist.py <email> [--reject] [--note "..."]` — одобрить
  или отклонить профиль психолога.
- `seed_dicts.py` — заполнить справочники.