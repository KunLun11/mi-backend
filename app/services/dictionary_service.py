"""Сервис справочников: подходы, IT-контексты и запросы клиентов."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approach, Concern, ITContextTag


async def list_approaches(db: AsyncSession) -> list[Approach]:
    """Вернуть все подходы, упорядоченные по ID."""
    result = await db.scalars(select(Approach).order_by(Approach.id))
    return list(result)


async def list_it_contexts(db: AsyncSession) -> list[ITContextTag]:
    """Вернуть все IT-контексты, упорядоченные по ID."""
    result = await db.scalars(select(ITContextTag).order_by(ITContextTag.id))
    return list(result)


async def list_concerns(db: AsyncSession) -> list[Concern]:
    """Вернуть все запросы клиентов, упорядоченные по ID."""
    result = await db.scalars(select(Concern).order_by(Concern.id))
    return list(result)
