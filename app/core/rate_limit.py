"""Rate limiting на Redis: атомарный INCR в фиксированном окне."""

import json
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.core.redis import get_redis

RateLimitSource = Literal["ip", "email"]


async def enforce_rate_limit(
    redis: Redis,
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Увеличить счётчик и выбросить 429 при превышении лимита."""
    current = int(await redis.incr(key))
    if current == 1:
        await redis.expire(key, window_seconds)

    if current > limit:
        retry_after = int(await redis.ttl(key))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


class RateLimit:
    """FastAPI-dependency: лимит по IP или по email из тела запроса."""

    def __init__(
        self,
        scope: str,
        limit: int,
        window_seconds: int,
        *,
        source: RateLimitSource = "ip",
        field: str = "email",
    ) -> None:
        self.scope = scope
        self.limit = limit
        self.window_seconds = window_seconds
        self.source = source
        self.field = field

    async def __call__(
        self,
        request: Request,
        redis: Redis = Depends(get_redis),
    ) -> None:
        identifier = await self._identifier(request)
        await enforce_rate_limit(
            redis,
            key=f"ratelimit:{self.scope}:{identifier}",
            limit=self.limit,
            window_seconds=self.window_seconds,
        )

    async def _identifier(self, request: Request) -> str:
        if self.source == "ip":
            client = request.client
            return client.host if client is not None else "unknown"

        raw_body = await request.body()
        try:
            data = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            return "unknown"
        if not isinstance(data, dict):
            return "unknown"

        value = data.get(self.field)
        if not value:
            return "unknown"
        return str(value).strip().lower()
