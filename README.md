# Mind IT — backend

MVP сервиса подбора психологов для IT-специалистов.

Работа ведётся по фазам из `docs/spec/05-phases.md`.

## Запуск (dev)

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health → `{"status":"ok"}`
- Mailhog UI: http://localhost:8025

## Зависимости (uv)

Проект управляется [uv](https://docs.astral.sh/uv/): версии фиксируются в `uv.lock`,
который **коммитится** в репозиторий. Python — 3.12 (см. `.python-version`).

```bash
uv add <package>            # добавить runtime-зависимость
uv add --dev <package>      # добавить dev-зависимость (группа dev)
uv remove <package>         # удалить зависимость
uv lock                     # пересчитать uv.lock
uv sync                     # поставить окружение ровно по uv.lock
```

После изменения зависимостей пересобери backend-образ:

```bash
docker compose build backend
docker compose up -d
```

## Локальный запуск без Docker

```bash
docker compose up -d postgres redis mailhog
uv sync
uv run uvicorn app.main:app --reload
```

## Миграции

```bash
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
```

В контейнере:

```bash
docker compose run --rm backend uv run alembic upgrade head
```

## Справочники (seed)

Идемпотентное заполнение подходов, IT-контекстов и запросов клиентов
(состав — `docs/spec/06-seed.md`):

```bash
uv run python -m scripts.seed_dicts
```

## Рекомендации куратора (CLI)

После того как клиент прошёл квиз, куратор вручную прикрепляет психолога
с обоснованием. Первая рекомендация переводит квиз в статус `recommended`:

```bash
uv run python -m scripts.recommend <quiz_id> <psychologist_id> "Почему выбран" [rank]
```

Психолог должен иметь `status=approved` в профиле.

## Модерация психологов (CLI)

Психолог заполняет профиль и отправляет его на проверку (`pending`).
Куратор одобряет или отклоняет профиль:

```bash
uv run python -m scripts.moderate_psychologist psy@example.com
uv run python -m scripts.moderate_psychologist psy@example.com --reject --note "Не хватает документов"
```

Одобрение выставляет `status=approved`, `supervision_confirmed` и
`is_verified_it_context`; после этого психолог видит входящие заявки.

## Фронтенд

```bash
cd ../mind_it_frontend
cp .env.example .env   # VITE_API_URL=http://localhost:8000/api/v1
npm install
npm run dev            # http://localhost:5173
```

## OAuth (Яндекс / Google / GitHub)

Ключи задаются в `.env`: `{PROVIDER}_CLIENT_ID`, `{PROVIDER}_CLIENT_SECRET`,
`{PROVIDER}_REDIRECT_URI`. Для локального запуска redirect URI — 
`http://localhost:8000/api/v1/auth/oauth/{provider}/callback`.

1. `GET /api/v1/auth/oauth/{provider}/authorize` → `{"authorize_url": "..."}`.
   `state` живёт `OAUTH_STATE_TTL_MINUTES` (10 минут) в Redis и одноразовый.
2. Провайдер возвращает браузер на callback с `code` и `state`;
   `GET /api/v1/auth/oauth/{provider}/callback` делает **302** на
   `{FRONTEND_URL}/auth/callback?access=...&refresh=...`.
3. Если аккаунт создан впервые (`role_selected=false`), роль выбирается через
   `POST /api/v1/auth/set-role` `{"role": "client" | "psychologist"}`.

Тесты OAuth не требуют реальных ключей: провайдеры мокаются через `respx`
(`tests/test_oauth_flow.py`).

