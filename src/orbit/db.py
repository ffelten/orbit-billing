"""Database connection dependency for API handlers."""

import os
from collections.abc import AsyncIterator

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://orbit:orbit@localhost:5433/orbit_test")


async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection for the lifetime of one request, then close it."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()
