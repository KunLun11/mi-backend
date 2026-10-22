"""CLI куратора: модерация профиля психолога.

Запуск (из каталога `mind_it_backend`):

    uv run python -m scripts.moderate_psychologist <email> [--reject] [--note "..."]

Одобрение переводит профиль в `approved`, отклонение — в `rejected`.
"""

import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.database import SessionFactory, dispose_engine
from app.models import PsychologistProfile, PsychologistStatus, User


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Одобрить или отклонить профиль психолога")
    parser.add_argument("email", help="Email психолога")
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Отклонить профиль вместо одобрения",
    )
    parser.add_argument("--note", default=None, help="Комментарий куратора для психолога")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    try:
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(func.lower(User.email) == args.email.lower()))
            if user is None:
                print(f"Ошибка: пользователь {args.email} не найден", file=sys.stderr)
                return 1

            profile = await db.get(PsychologistProfile, user.id)
            if profile is None:
                print(f"Ошибка: у {args.email} нет профиля психолога", file=sys.stderr)
                return 1

            if args.reject:
                profile.status = PsychologistStatus.REJECTED
            else:
                profile.status = PsychologistStatus.APPROVED
                profile.supervision_confirmed = True
                profile.is_verified_it_context = True

            if args.note is not None:
                profile.verification_notes = args.note

            await db.commit()
            print(f"Профиль {args.email}: статус {profile.status.value}")
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    """Точка входа CLI."""
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
