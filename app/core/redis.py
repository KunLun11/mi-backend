"""Async-клиент Redis для rate limiting, blacklist и reuse detection."""

from collections.abc import AsyncIterator

from redis.asyncio import Redis, from_url

from app.config import get_settings

settings = get_settings()

redis_client: Redis = from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI-dependency: общий асинхронный клиент Redis."""
    yield redis_client


async def close_redis() -> None:
    """Закрыть соединения Redis при остановке приложения."""
    await redis_client.aclose()
