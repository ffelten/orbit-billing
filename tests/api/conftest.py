from collections.abc import AsyncIterator

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orbit.api.routes import router
from orbit.db import get_connection


@pytest.fixture
def app(db_conn: asyncpg.Connection) -> FastAPI:
    """A FastAPI app with the real router, its DB dependency pointed at `db_conn`."""
    app = FastAPI()
    app.include_router(router)

    async def _override_get_connection() -> AsyncIterator[asyncpg.Connection]:
        yield db_conn

    app.dependency_overrides[get_connection] = _override_get_connection
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
