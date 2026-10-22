"""CLI куратора: добавить рекомендацию психолога к квизу.

Запуск (из каталога `mind_it_backend`):

    uv run python -m scripts.recommend <quiz_id> <psychologist_id> "<admin_note>" [rank]

После первой рекомендации квиз переходит в статус `recommended`.
"""

import argparse
import asyncio
import sys
from uuid import UUID

from fastapi import HTTPException

from app.database import SessionFactory, dispose_engine
from app.schemas.quizzes import RecommendationCreate
from app.services import recommendation_service


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Добавить рекомендацию психолога к квизу")
    parser.add_argument("quiz_id", type=UUID, help="ID квиза (UUID)")
    parser.add_argument("psychologist_id", type=UUID, help="ID пользователя-психолога (UUID)")
    parser.add_argument("admin_note", help="Обоснование куратора для клиента")
    parser.add_argument("rank", nargs="?", type=int, default=None, help="Порядковый номер")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    try:
        async with SessionFactory() as db:
            try:
                recommendation = await recommendation_service.create_recommendation(
                    db,
                    RecommendationCreate(
                        quiz_id=args.quiz_id,
                        psychologist_id=args.psychologist_id,
                        admin_note=args.admin_note,
                        rank=args.rank,
                    ),
                )
            except HTTPException as exc:
                print(f"Ошибка: {exc.detail}", file=sys.stderr)
                return 1

            print(
                "Рекомендация сохранена: "
                f"id={recommendation.id} quiz={recommendation.quiz_id} "
                f"psychologist={recommendation.psychologist_id} rank={recommendation.rank}"
            )
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    """Точка входа CLI."""
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
