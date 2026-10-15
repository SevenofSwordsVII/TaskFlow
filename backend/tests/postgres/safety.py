"""PostgreSQL integration test database safety and validation guards."""

import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

BLOCKED_DATABASE_NAMES = {
    "taskflow",
    "postgres",
    "template0",
    "template1",
    "production",
    "prod",
    "staging",
    "master",
    "main",
    "dev",
    "development",
}

DEFAULT_TEST_DB_NAME = "taskflow_test"
DEFAULT_TEST_DB_URL = "postgresql+asyncpg://taskflow:change-me@localhost:5432/taskflow_test"


class DatabaseSafetyError(RuntimeError):
    """Raised when integration test database validation fails."""

    pass


def get_raw_test_database_url() -> str:
    """Retrieve test database URL strictly without falling back to application database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        # Default to dedicated test database URL if not explicitly provided
        url = DEFAULT_TEST_DB_URL
    return url


def validate_test_database_url(url_string: str) -> URL:
    """Parse and validate database URL to ensure it targets a safe, disposable test database.

    Guards:
    1. Parse with SQLAlchemy make_url.
    2. Ensure dialect is postgresql/asyncpg.
    3. Ensure database name is explicitly test-specific (ends with '_test' or contains 'test').
    4. Reject if database name matches configured dev database or any known production database.
    5. Mask credentials in any generated logs/errors.
    """
    try:
        parsed: URL = make_url(url_string)
    except Exception as exc:
        raise DatabaseSafetyError(f"Invalid TEST_DATABASE_URL format: {exc}") from exc

    db_name = parsed.database
    if not db_name:
        raise DatabaseSafetyError("TEST_DATABASE_URL must specify a target database name.")

    # Guard 1: Prohibit application's configured development database
    dev_db_name = settings.POSTGRES_DB.lower()
    if db_name.lower() == dev_db_name:
        raise DatabaseSafetyError(
            f"REFUSED: TEST_DATABASE_URL targets configured development database '{dev_db_name}'. "
            "Tests must run against an isolated test database (e.g. taskflow_test)."
        )

    # Guard 2: Prohibit known system or production database names
    if db_name.lower() in BLOCKED_DATABASE_NAMES:
        raise DatabaseSafetyError(
            f"REFUSED: Database name '{db_name}' is in the blocked databases list. "
            "Target database must be dedicated strictly to testing."
        )

    # Guard 3: Require explicit test identifier in database name
    if "test" not in db_name.lower():
        raise DatabaseSafetyError(
            f"REFUSED: Database name '{db_name}' must contain 'test' (e.g. 'taskflow_test')."
        )

    # Guard 4: Driver compatibility
    if not parsed.drivername.startswith("postgresql"):
        raise DatabaseSafetyError(
            f"REFUSED: Expected postgresql driver, got '{parsed.drivername}'."
        )

    return parsed


def get_safe_masked_url(url: URL | str) -> str:
    """Return URL representation with password masked."""
    if isinstance(url, str):
        url = make_url(url)
    return url.render_as_string(hide_password=True)


async def verify_connected_database(engine_url: str) -> None:
    """Connect to database and verify current_database() matches validated test database.

    Prevents running any DDL, migration, or cleanup against an unintended target.
    """
    parsed = validate_test_database_url(engine_url)
    target_db = parsed.database

    test_engine = create_async_engine(engine_url, echo=False)
    try:
        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT current_database();"))
            connected_db = result.scalar()

            if connected_db != target_db:
                raise DatabaseSafetyError(
                    f"Safety check mismatch: connected to '{connected_db}' "
                    f"but expected test database '{target_db}'."
                )

            # Extra check: confirm again it is not the development DB
            if connected_db == settings.POSTGRES_DB:
                raise DatabaseSafetyError(
                    f"CRITICAL: Connected to development database '{connected_db}'!"
                )
    finally:
        await test_engine.dispose()
