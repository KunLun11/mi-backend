# 02 — Аутентификация

## Конфиг (`Settings`)

ACCESS_TOKEN_TTL_MINUTES=45
REFRESH_TOKEN_TTL_DAYS=30
SESSION_IDLE_TIMEOUT_DAYS=7
EMAIL_CODE_TTL_MINUTES=15
JWT_ALGORITHM=HS256
JWT_ISSUER=psy-it
COMMISSION_FIXED_RUB=500


## Email-регистрация
1. `POST /api/v1/auth/register` `{email, password, role}` →
   создаёт `User` (`email_verified=False`, argon2), профиль
   (`ClientProfile` или `PsychologistProfile` со `status=draft`),
   6-значный код (TTL 15 мин, хранится **хеш**), письмо через Mailhog.
   204.
2. `POST /api/v1/auth/verify-email` `{email, code}` →
   сверка хеша, `email_verified=True`, `consumed_at=now()`,
   возвращает `TokenResponse`.
3. `POST /api/v1/auth/resend-code` `{email}`, rate limit 1/60 сек (Redis).

## Login
`POST /api/v1/auth/login` `{email, password}`. Если `email_verified=False` —
403 `email_not_verified`. Создаёт `UserSession`, возвращает `TokenResponse`.

## OAuth2 (authlib)
Провайдеры: Yandex (обязательно), Google, GitHub.
`{PROVIDER}_CLIENT_ID`, `{PROVIDER}_CLIENT_SECRET`, `{PROVIDER}_REDIRECT_URI`
в `Settings`. `OAUTH_STATE_TTL_MINUTES=10`.

1. `GET /api/v1/auth/oauth/{provider}/authorize` → state в Redis → `{authorize_url}`.
2. `GET /api/v1/auth/oauth/{provider}/callback?code&state` → проверка state
   (одноразово) → обмен code → профиль через authlib. Логика:
   - есть `OAuthAccount` по (`provider`,`provider_user_id`) → логин;
   - иначе ищем `User` по `provider_email` → привязка нового `OAuthAccount`;
   - иначе новый `User` (`email_verified=True`, `password_hash=None`,
     `role=client`, `role_selected=False`) + `ClientProfile` + `OAuthAccount`.
   Создаёт `UserSession`, возвращает `TokenResponse`.
   Токены провайдера в JWT **не кладём**. На MVP в `OAuthAccount` — `None`.
3. `POST /api/v1/auth/set-role` `{role}` (JWT) — только если `role_selected=False`,
   создаёт профиль, ставит `role_selected=True`.

## Токены и сессии
`TokenResponse`: `{access_token, refresh_token, token_type="bearer", expires_in}`.

Access (JWT): `{sub, role, jti: uuid, iat, exp, iss, type:"access"}`, TTL 45 мин.
Refresh: opaque 64 байта base64url, в БД — `sha256(...)` в `refresh_token_hash`.

`create_session`: `family_id=uuid4()`, `expires_at=now()+30д`,
`last_used_at=now()`, `user_agent`, `ip_address`.

`POST /api/v1/auth/refresh` `{refresh_token}`:
1. Найти `UserSession` по `sha256(refresh_token)`; нет → 401.
2. `revoked_at IS NOT NULL` → 401.
3. `now > expires_at` (absolute) → 401, `revoked_at=now()`.
4. `now - last_used_at > 7д` (idle) → 401, `revoked_at=now()`.
5. Reuse detection: `rotation_counter` не совпадает → отозвать **всю**
   `family_id` (`revoked_at=now()` для всех с этим `family_id`), 401.
6. Иначе: `rotation_counter+=1`, новый `refresh_token_hash`,
   `last_used_at=now()`, вернуть новый `TokenResponse`.

`POST /api/v1/auth/logout` `{refresh_token}` → `revoked_at=now()`,
`jti` текущего access → Redis `blacklist:{jti}` с TTL `exp - now`.

`POST /api/v1/auth/logout-all` (JWT) → `revoked_at=now()` для всех сессий,
текущий `jti` → Redis blacklist.

`deps.get_current_user`: декод JWT → проверка `exp/iss/type` → `jti` в Redis
`blacklist:*` → загрузка `User` → `is_active`.

## Rate limiting (Redis)
- `register`: 5 / 1ч / IP
- `login`: 10 / 15м / IP
- `verify-email`: 5 / 15м / email
- `resend-code`: 1 / 60с / email

Реализовать как FastAPI dependency `rate_limit(key, limit, window)`.

## Хранение кода
Код верификации хранится **только** как хеш (`sha256`). Сырой код — только
в письме. Argon2 — только для паролей.