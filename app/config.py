"""Конфигурация приложения: единственный источник настроек — pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Настройки приложения, читаемые из переменных окружения и `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Приложение
    app_name: str = "Mind IT"
    app_env: str = "dev"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "mind_it"
    postgres_password: str = "mind_it"
    postgres_db: str = "mind_it"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT / сессии
    jwt_secret: str = "dev-insecure-secret-change-me-please-32b"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "psy-it"
    access_token_ttl_minutes: int = 45
    refresh_token_ttl_days: int = 30
    session_idle_timeout_days: int = 7
    email_code_ttl_minutes: int = 15
    oauth_state_ttl_minutes: int = 10

    # Комиссия
    commission_fixed_rub: int = 500

    # Email (Mailhog в dev)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@mind-it.local"
    smtp_tls: bool = False

    # OAuth-провайдеры
    yandex_client_id: str | None = None
    yandex_client_secret: str | None = None
    yandex_redirect_uri: str | None = None

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None

    @property
    def database_url(self) -> str:
        """DSN для async-движка SQLAlchemy (asyncpg)."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    """Вернуть кешированный экземпляр настроек."""
    return Settings()
