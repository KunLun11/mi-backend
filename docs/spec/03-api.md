# 03 — API (префикс `/api/v1`)

Авторизация — Bearer JWT, кроме `/auth/*` и `/health`.

## Auth
- `POST /auth/register` `{email, password, role}` → 204
- `POST /auth/verify-email` `{email, code}` → `TokenResponse`
- `POST /auth/resend-code` `{email}` → 204
- `POST /auth/login` `{email, password}` → `TokenResponse`
- `POST /auth/refresh` `{refresh_token}` → `TokenResponse`
- `POST /auth/logout` `{refresh_token}` → 204
- `POST /auth/logout-all` → 204
- `POST /auth/set-role` `{role}` → `UserPublic`
- `GET  /auth/oauth/{provider}/authorize` → `{authorize_url}`
- `GET  /auth/oauth/{provider}/callback?code&state` → `TokenResponse`
- `GET  /auth/me` → `UserPublic + profile`

## Clients
- `GET  /clients/me` → `ClientProfileOut`
- `PUT  /clients/me` `ClientProfileIn` → `ClientProfileOut`

## Psychologists
- `GET  /psychologists/me` → `PsychologistProfileOut`
- `PUT  /psychologists/me` `PsychologistProfileIn` → `PsychologistProfileOut`
- `POST /psychologists/me/submit` → `PsychologistProfileOut` (draft→pending)
- `GET  /psychologists` (фильтры: `approach`, `it_context`, `format`,
  пагинация) → `{items, total}` — только `approved`
- `GET  /psychologists/{id}` — только `approved`

## Quizzes
- `POST /quizzes` `QuizIn` → `QuizOut`
- `GET  /quizzes/{id}` → `QuizOut` (свой)
- `GET  /quizzes/{id}/recommendations` → `RecommendationOut[]`
  (только при `status=recommended`)

## Session Requests
- `POST /session-requests` `{recommendation_id, message?, preferred_time?}`
  → `SessionRequestOut` (client)
- `GET  /session-requests` → список своих (client — как клиент,
  psychologist — как психолог)
- `POST /session-requests/{id}/accept` `{scheduled_at, price_rub}`
  → `TherapySessionOut` (psychologist)
- `POST /session-requests/{id}/decline` → `SessionRequestOut`
- `POST /session-requests/{id}/cancel` → `SessionRequestOut`

## Sessions
- `GET  /sessions` → список своих
- `POST /sessions/{id}/complete` → `TherapySessionOut` + создаёт `Commission`
- `POST /sessions/{id}/no-show` → `TherapySessionOut`

## Health
- `GET /health` → `{status: "ok"}`

## Форматы ошибок
`HTTPException(detail="snake_case_code")` — например `email_not_verified`,
`invalid_credentials`, `quiz_not_ready`, `psychologist_not_approved`.