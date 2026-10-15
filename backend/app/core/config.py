"""TaskFlow configuration settings management."""

import os
from typing import Any


def parse_cors_origins(v: Any) -> list[str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list):
        return [str(i) for i in v]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def parse_trusted_proxies(v: Any) -> list[str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list):
        return [str(i).strip() for i in v if str(i).strip()]
    return []


try:
    from typing import Annotated

    from pydantic import BeforeValidator, computed_field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=True,
            extra="ignore",
        )

        ENVIRONMENT: str = "development"
        PROJECT_NAME: str = "TaskFlow"
        API_V1_STR: str = "/api/v1"

        # Security & Tokens
        SECRET_KEY: str = "taskflow-super-secret-development-key-change-in-production-min-32-chars"
        ADMIN_SECRET_KEY: str | None = None
        REFRESH_RECOVERY_KEY: str = "taskflow-recovery-key-change-in-prod-32b!"
        ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
        REFRESH_TOKEN_EXPIRE_DAYS: int = 30
        ALGORITHM: str = "HS256"

        @property
        def effective_admin_secret_key(self) -> str:
            return self.ADMIN_SECRET_KEY or self.SECRET_KEY

        # Database
        POSTGRES_SERVER: str = "localhost"
        POSTGRES_PORT: int = 5432
        POSTGRES_USER: str = "taskflow"
        POSTGRES_PASSWORD: str = "change-me"
        POSTGRES_DB: str = "taskflow"
        DATABASE_URL: str | None = None

        DB_POOL_SIZE: int = 10
        DB_MAX_OVERFLOW: int = 20
        DB_POOL_TIMEOUT: int = 30
        DB_POOL_RECYCLE: int = 1800

        # CORS & Cookies
        ALLOWED_ORIGINS: Annotated[list[str], BeforeValidator(parse_cors_origins)] = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        SAME_SITE: str = "lax"
        COOKIE_SECURE: bool = False
        COOKIE_DOMAIN: str | None = None

        # Reverse Proxy & Rate Limiting
        TRUSTED_PROXIES: Annotated[list[str], BeforeValidator(parse_trusted_proxies)] = []

        @computed_field  # type: ignore[prop-decorator]
        @property
        def async_database_url(self) -> str:
            if self.DATABASE_URL:
                url = self.DATABASE_URL
                if url.startswith("postgresql://"):
                    return url.replace("postgresql://", "postgresql+asyncpg://", 1)
                elif url.startswith("postgres://"):
                    return url.replace("postgres://", "postgresql+asyncpg://", 1)
                return url
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
                f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

    settings = Settings()

except ImportError:
    # Graceful fallback for offline bare environments before Docker / pip install
    class Settings:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self.ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
            self.PROJECT_NAME = os.getenv("PROJECT_NAME", "TaskFlow")
            self.API_V1_STR = os.getenv("API_V1_STR", "/api/v1")
            self.SECRET_KEY = os.getenv(
                "SECRET_KEY",
                "taskflow-super-secret-development-key-change-in-production-min-32-chars",
            )
            self.ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
            self.REFRESH_RECOVERY_KEY = os.getenv(
                "REFRESH_RECOVERY_KEY",
                "taskflow-recovery-key-change-in-prod-32b!",
            )
            self.ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
            self.REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
            self.ALGORITHM = os.getenv("ALGORITHM", "HS256")

            self.POSTGRES_SERVER = os.getenv("POSTGRES_SERVER", "localhost")
            self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
            self.POSTGRES_USER = os.getenv("POSTGRES_USER", "taskflow")
            self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "change-me")
            self.POSTGRES_DB = os.getenv("POSTGRES_DB", "taskflow")
            self.DATABASE_URL = os.getenv("DATABASE_URL")

            self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
            self.DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
            self.DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
            self.DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

            self.ALLOWED_ORIGINS = parse_cors_origins(
                os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
            )
            self.SAME_SITE = os.getenv("SAME_SITE", "lax")
            self.COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
            self.COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN")
            self.TRUSTED_PROXIES = parse_trusted_proxies(os.getenv("TRUSTED_PROXIES", ""))

        @property
        def effective_admin_secret_key(self) -> str:
            return self.ADMIN_SECRET_KEY or self.SECRET_KEY

        @property
        def async_database_url(self) -> str:
            if self.DATABASE_URL:
                url = self.DATABASE_URL
                if url.startswith("postgresql://"):
                    return url.replace("postgresql://", "postgresql+asyncpg://", 1)
                elif url.startswith("postgres://"):
                    return url.replace("postgres://", "postgresql+asyncpg://", 1)
                return url
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
                f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

    settings = Settings()
