import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbit.api.routes import router

_ADMIN_SCOPE_HEADERS = {"X-Admin-Scopes": "admin:gift-cards"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


async def _seed_customer(conn: asyncpg.Connection, email: str = "corp@example.com") -> int:
    return await conn.fetchval("INSERT INTO customers (email) VALUES ($1) RETURNING id", email)


async def test_bulk_issue_creates_requested_number_of_cards(
    client: TestClient, db_conn: asyncpg.Connection
) -> None:
    customer_id = await _seed_customer(db_conn)

    response = client.post(
        "/admin/gift-cards/bulk",
        json={"customer_id": customer_id, "count": 3, "face_value_cents": 5000},
        headers=_ADMIN_SCOPE_HEADERS,
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["gift_cards"]) == 3
    assert len({gc["code"] for gc in body["gift_cards"]}) == 3
    assert {gc["face_value_cents"] for gc in body["gift_cards"]} == {5000}

    stored_count = await db_conn.fetchval(
        "SELECT count(*) FROM gift_cards WHERE customer_id = $1", customer_id
    )
    assert stored_count == 3


async def test_bulk_issue_without_scope_is_forbidden(
    client: TestClient, db_conn: asyncpg.Connection
) -> None:
    customer_id = await _seed_customer(db_conn)

    response = client.post(
        "/admin/gift-cards/bulk",
        json={"customer_id": customer_id, "count": 3, "face_value_cents": 5000},
    )

    assert response.status_code == 403
    stored_count = await db_conn.fetchval(
        "SELECT count(*) FROM gift_cards WHERE customer_id = $1", customer_id
    )
    assert stored_count == 0


async def test_bulk_issue_unknown_customer_is_not_found(
    client: TestClient, db_conn: asyncpg.Connection
) -> None:
    response = client.post(
        "/admin/gift-cards/bulk",
        json={"customer_id": 999999, "count": 3, "face_value_cents": 5000},
        headers=_ADMIN_SCOPE_HEADERS,
    )

    assert response.status_code == 404
    stored_count = await db_conn.fetchval("SELECT count(*) FROM gift_cards")
    assert stored_count == 0


async def test_bulk_issue_zero_count_is_rejected(
    client: TestClient, db_conn: asyncpg.Connection
) -> None:
    customer_id = await _seed_customer(db_conn)

    response = client.post(
        "/admin/gift-cards/bulk",
        json={"customer_id": customer_id, "count": 0, "face_value_cents": 5000},
        headers=_ADMIN_SCOPE_HEADERS,
    )

    assert response.status_code == 422
    stored_count = await db_conn.fetchval(
        "SELECT count(*) FROM gift_cards WHERE customer_id = $1", customer_id
    )
    assert stored_count == 0
