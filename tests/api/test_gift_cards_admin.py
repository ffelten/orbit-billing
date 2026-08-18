import asyncpg
import pytest
from httpx import AsyncClient

_ADMIN_KEY = "sk_test_51HxExampleFakeKeyDoNotUseabcdef0000"
_SCOPE = "admin:gift-cards"


async def _seed_customer(conn: asyncpg.Connection, *, email: str = "corp@example.com") -> int:
    return await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", email
    )


async def test_bulk_issue_without_admin_key_returns_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", _ADMIN_KEY)
    monkeypatch.setenv("ADMIN_API_KEY_SCOPES", _SCOPE)

    response = await client.post(
        "/admin/gift-cards/bulk",
        json={"purchaser_customer_id": 1, "amount_cents": 5000, "count": 3},
    )

    assert response.status_code == 401


async def test_bulk_issue_with_wrong_admin_key_returns_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", _ADMIN_KEY)
    monkeypatch.setenv("ADMIN_API_KEY_SCOPES", _SCOPE)

    response = await client.post(
        "/admin/gift-cards/bulk",
        json={"purchaser_customer_id": 1, "amount_cents": 5000, "count": 3},
        headers={"X-Admin-Key": "wrong-key"},
    )

    assert response.status_code == 401


async def test_bulk_issue_with_key_missing_scope_returns_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", _ADMIN_KEY)
    monkeypatch.setenv("ADMIN_API_KEY_SCOPES", "admin:refunds")

    response = await client.post(
        "/admin/gift-cards/bulk",
        json={"purchaser_customer_id": 1, "amount_cents": 5000, "count": 3},
        headers={"X-Admin-Key": _ADMIN_KEY},
    )

    assert response.status_code == 403


async def test_bulk_issue_with_valid_key_and_scope_issues_n_cards(
    client: AsyncClient, db_conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", _ADMIN_KEY)
    monkeypatch.setenv("ADMIN_API_KEY_SCOPES", _SCOPE)
    customer_id = await _seed_customer(db_conn)

    response = await client.post(
        "/admin/gift-cards/bulk",
        json={"purchaser_customer_id": customer_id, "amount_cents": 5000, "count": 3},
        headers={"X-Admin-Key": _ADMIN_KEY},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["gift_cards"]) == 3
    assert {gc["face_value_cents"] for gc in body["gift_cards"]} == {5000}
    assert len({gc["code"] for gc in body["gift_cards"]}) == 3

    stored_count = await db_conn.fetchval(
        "SELECT count(*) FROM gift_cards WHERE purchaser_customer_id = $1", customer_id
    )
    assert stored_count == 3
