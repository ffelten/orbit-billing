import os
import pathlib
from collections.abc import AsyncIterator

import asyncpg
import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://orbit:orbit@localhost:5433/orbit_test")
MIGRATIONS_SQL = (pathlib.Path(__file__).parent.parent / "migrations" / "001_init.sql").read_text()


@pytest.fixture
async def db_conn() -> AsyncIterator[asyncpg.Connection]:
    """A connection to a scratch Postgres database, reset to a fresh schema per test."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute(MIGRATIONS_SQL)
        yield conn
    finally:
        await conn.close()
