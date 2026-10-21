"""Общие фикстуры: тестовая БД, отдельная Redis DB и ASGI-клиент."""

import logging
import os

# Переменные должны быть выставлены до импорта app.*: engine и Redis создаются
# на уровне модулей.
os.environ["POSTGRES_DB"] = "mind_it_test"
os.environ["REDIS_URL"] = "redis://localhost:6380/15"
os.environ["SMTP_HOST"] = "localhost"
os.environ["SMTP_PORT"] = "1025"
os.environ["SMTP_TLS"] = "false"
os.environ["DEBUG"] = "false"

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.redis import redis_client  # noqa: E402
from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

settings = get_settings()

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _recreate_test_database() -> None:
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{settings.postgres_db}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await connection.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def prepare_database():
    """Пересоздать тестовую БД и накатить схему из метаданных."""
    await _recreate_test_database()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()
    await redis_client.aclose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_state(prepare_database):
    """Очистить таблицы и Redis перед каждым тестом."""
    await redis_client.flushdb()
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    yield


@pytest_asyncio.fixture(loop_scope="session")
async def client(prepare_database):
    """HTTP-клиент поверх ASGI-приложения (без реального сокета)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
