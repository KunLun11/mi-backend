# AGENTS.md — правила для AI-агентов

Единый источник правды для любого агента (Copilot, Cline, Roo, Continue, Aider).
При конфликте с любым другим файлом — приоритет у этого.

## Продукт

MVP сервиса подбора психологов для IT-специалистов.
Ключевая фишка MVP — **ручной кураторский подбор**: админ видит ответы квиза и
вручную прикрепляет 1–3 психолога с текстовым обоснованием. Алгоритмического
матчинга, платежей, чатов, отзывов, WebSocket на MVP **нет**.

## Стек (строго)

Backend: Python 3.12+, FastAPI (async), SQLAlchemy 2.0 (Mapped/mapped_column),
Pydantic v2 + pydantic-settings, Alembic (async), PostgreSQL 16, Redis 7,
authlib (OAuth2: Yandex/Google/GitHub), python-jose, passlib[argon2],
aiosmtplib + jinja2, httpx, asyncpg.

Frontend: TypeScript, Vite, React 18, React Router, TanStack Query,
Zustand, Axios (interceptor для refresh), TailwindCSS. Без UI-kit на MVP.

Инфраструктура: Docker Compose — postgres, redis, backend, frontend, mailhog (dev).
Конфиг — только через pydantic-settings, `.env.example` в репо.
Пакетный менеджер — **uv** (`uv add` / `uv sync`, `uv.lock` коммитится).
Python — 3.12 (`.python-version`).

## Структура

backend/app/{main.py, config.py, database.py, models/, schemas/, api/v1/,
services/, core/}, backend/alembic/, backend/tests/, backend/pyproject.toml,
frontend/src/{api/, components/, pages/, hooks/, store/, types/},
docs/spec/, docker-compose.yml, README.md.

Полная структура — `docs/spec/05-phases.md`, раздел «Структура».

## Правила кодирования (backend)

1. Все модели — SQLAlchemy 2.0 стиль: `Mapped[...]` + `mapped_column(...)`.
   Никаких `Column(...)`.
2. Все Enum — `StrEnum` + `SAEnum(..., native_enum=False, length=32)`.
   Никаких нативных PG ENUM, никаких числовых кодов.
3. Все Pydantic-схемы — v2. Для ORM-моделей `model_config = {"from_attributes": True}`.
4. Все эндпоинты — `async def`. Синхронные операции (argon2) — через
   `asyncio.to_thread` или async-библиотеки.
5. Бизнес-логика только в `services/`. Роутер: валидация → сервис → схема.
6. Все ID — `UUID v4` (`uuid.uuid4`), кроме справочников
   (`Approach`, `ITContextTag`, `Concern` — `Integer` autoincrement).
7. Все timestamps — `DateTime(timezone=True)`, `server_default=func.now()`,
   для обновляемых — `onupdate=func.now()`.
8. Ошибки — через `HTTPException` с осмысленным `detail` (snake_case код).
9. Секреты — только через `Settings`. Никаких хардкодов.
10. Логирование — только `logging` через `core/logging.py`. Никаких `print`.
11. Тесты — обязательны для auth-флоу и переходов статусов
    (happy-path + 2–3 edge-case на сервис).
12. OpenAPI — источник типов для фронта: после изменения API запускай
    `openapi-typescript` и коммить `frontend/src/types/api.ts`.
13. Форматирование: `ruff format` + `ruff check`, `mypy --strict` для
    `models/` и `services/`.

## Правила кодирования (frontend)

1. Только функциональные компоненты + хуки. Никаких классов.
2. Типы API — генерируются из OpenAPI, не пишутся руками.
3. Состояние: серверное — TanStack Query, клиентское — Zustand.
   Не дублировать серверное состояние в Zustand.
4. Все запросы — через `src/api/` (обёртки над Axios), не напрямую в компонентах.
5. Axios interceptor: при 401 → попытка refresh → при неудаче logout + redirect.
6. Стили — Tailwind utility-классы. Без кастомного CSS, если можно обойтись.

## Запрещено на MVP

- Django, DRF, SQLModel, Tortoise ORM, `psycopg2` (только `asyncpg`).
- Алгоритмический матчинг, платежи/эквайринг, чаты, отзывы/рейтинги,
  WebSocket, push, i18n.
- Админка на фронте — только CLI-скрипты в `backend/scripts/`.
- Email-уведомления о смене статусов (кроме кода верификации).
- Тесты на фронте (ручное тестирование для MVP достаточно).

## Workflow

Работай по фазам из `docs/spec/05-phases.md`. Одна фаза за раз.
После каждой фазы — стоп, покажи результат, дождись подтверждения.
Если требование противоречиво — задай вопрос, не додумывай.
Критерий готовности каждой фазы — в её разделе (acceptance).

## Definition of Done (MVP)

1. `docker compose up` поднимает весь стек.
2. Сквозной сценарий проходит в браузере: регистрация → verify → квиз →
   (CLI: рекомендация) → заявка → (второй аккаунт/CLI: принятие) → сессия →
   (CLI/второй аккаунт: completed) → комиссия в БД.
3. OAuth Яндекс работает в dev (реальные ключи в `.env`).
4. Refresh-rotation + reuse detection покрыты тестами.
5. Blacklist access-токенов в Redis работает (logout → старый токен 401).
6. Idle 7 дней и absolute 30 дней реализованы.
7. `pytest` зелёный, `ruff check` и `mypy --strict` чистые.
8. `README.md` содержит запуск и список CLI-скриптов.

## Детали

- Модели: `docs/spec/01-models.md`
- Аутентификация: `docs/spec/02-auth.md`
- API: `docs/spec/03-api.md`
- Бизнес-логика: `docs/spec/04-business-logic.md`
- Фазы: `docs/spec/05-phases.md`
- Справочники: `docs/spec/06-seed.md`