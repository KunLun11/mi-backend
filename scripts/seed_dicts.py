"""Идемпотентно заполнить справочники: подходы, IT-контексты, запросы.

Запуск (из каталога `mind_it_backend`):

    uv run python -m scripts.seed_dicts

Повторный запуск не дублирует записи: существующие обновляются по `slug`.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging
from app.database import SessionFactory, dispose_engine
from app.models import Approach, Concern, ITContextTag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DictionaryEntry:
    """Элемент справочника для сидирования."""

    slug: str
    name: str


APPROACHES: tuple[DictionaryEntry, ...] = (
    DictionaryEntry("cbt", "Когнитивно-поведенческая терапия"),
    DictionaryEntry("act", "Терапия принятия и ответственности (ACT)"),
    DictionaryEntry("psychodynamic", "Психодинамическая терапия"),
    DictionaryEntry("systemic", "Системная семейная терапия"),
    DictionaryEntry("gestalt", "Гештальт-терапия"),
)

IT_CONTEXTS: tuple[DictionaryEntry, ...] = (
    DictionaryEntry("burnout", "Выгорание"),
    DictionaryEntry("imposter_syndrome", "Синдром самозванца"),
    DictionaryEntry("perfectionism", "Перфекционизм"),
    DictionaryEntry("procrastination", "Прокрастинация"),
    DictionaryEntry("manager_stress", "Стресс руководителя"),
    DictionaryEntry("layoff_anxiety", "Тревога из-за сокращений"),
    DictionaryEntry("career_change", "Смена профессии"),
    DictionaryEntry("remote_isolation", "Изоляция на удалёнке"),
    DictionaryEntry("overtime", "Переработки и отсутствие границ"),
    DictionaryEntry("tech_anxiety", "Тревога из-за технологий и ИИ"),
    DictionaryEntry("team_conflict", "Конфликты в команде"),
    DictionaryEntry("interview_anxiety", "Тревога перед собеседованиями"),
)

CONCERNS: tuple[DictionaryEntry, ...] = (
    DictionaryEntry("anxiety", "Тревога"),
    DictionaryEntry("depression", "Депрессивные состояния"),
    DictionaryEntry("burnout", "Выгорание"),
    DictionaryEntry("relationships", "Отношения"),
    DictionaryEntry("self_esteem", "Самооценка"),
    DictionaryEntry("stress", "Стресс"),
    DictionaryEntry("grief", "Утрата"),
    DictionaryEntry("sleep", "Нарушения сна"),
)


async def _sync(
    db: AsyncSession,
    model: type[Approach] | type[ITContextTag] | type[Concern],
    entries: tuple[DictionaryEntry, ...],
) -> tuple[int, int]:
    """Создать отсутствующие записи и обновить названия существующих."""
    existing = {item.slug: item for item in (await db.scalars(select(model))).all()}

    created = 0
    updated = 0
    for entry in entries:
        item = existing.get(entry.slug)
        if item is None:
            db.add(model(slug=entry.slug, name=entry.name))
            created += 1
        elif item.name != entry.name:
            item.name = entry.name
            updated += 1

    return created, updated


async def seed_dictionaries() -> None:
    """Заполнить все справочники в одной транзакции."""
    async with SessionFactory() as db:
        created_approaches, updated_approaches = await _sync(db, Approach, APPROACHES)
        created_contexts, updated_contexts = await _sync(db, ITContextTag, IT_CONTEXTS)
        created_concerns, updated_concerns = await _sync(db, Concern, CONCERNS)
        await db.commit()

    logger.info(
        "approaches: +%d/~%d, it_contexts: +%d/~%d, concerns: +%d/~%d",
        created_approaches,
        updated_approaches,
        created_contexts,
        updated_contexts,
        created_concerns,
        updated_concerns,
    )


async def main() -> None:
    """Точка входа CLI."""
    configure_logging()
    try:
        await seed_dictionaries()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
