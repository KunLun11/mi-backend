# 04 — Бизнес-логика и переходы статусов

## QuizResponse
`submitted → processing → recommended → closed`.
`processing → recommended` — только при создании ≥ 1 `Recommendation`
(в `recommendation_service.create`). Прямое изменение статуса в роутере
запрещено — только через сервис.

## SessionRequest
- `pending → accepted` (psychologist, `accept`) — создаёт `TherapySession`.
- `pending → declined` (psychologist).
- `pending | accepted → cancelled` (client или psychologist).
- `accepted → completed` — неявно, через `TherapySession.completed`.
  При `complete` на сессии request помечается `completed`.

## TherapySession
Создаётся только из `accepted` request (1:1).
`scheduled → completed | no_show | cancelled`.
`complete` (psychologist): `status=completed`, `completed_at=now()`,
создаёт `Commission` через `commission_service`.

## Commission
Создаётся только при `session.completed`. `amount_rub`:
- `fixed` — `Settings.COMMISSION_FIXED_RUB` (500 на MVP, `rate_value=500`);
- `percent` — `percent * session.price_rub / 100`
  (`rate_value=10.00`). Модель поддерживает оба, на MVP **fixed**.

## PsychologistProfile
Принимать заявки можно только при `status=approved`.
Заявки, созданные когда психолог был `approved`, но потом отклонён, —
не отзываем; новые не создаются (`403 psychologist_not_approved`).

## Права
- Client: свои квизы, заявки, сессии; создание заявки только из
  `recommended` квиза.
- Psychologist: свой профиль, входящие заявки (только `approved`),
  `accept/decline`, `complete/no-show` своих сессий.
- Admin: на MVP — только CLI-скрипты; API админа не делаем.