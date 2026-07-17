from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.idempotency import NewChargeRequest, get_or_create_charge_for_event

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


async def _seed_subscription(conn: asyncpg.Connection) -> int:
    customer_id = await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", "customer@example.com"
    )
    plan_id = await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) VALUES ($1, $2, $3) RETURNING id",
        "Pro Monthly",
        1999,
        "monthly",
    )
    return await conn.fetchval(
        """
        INSERT INTO subscriptions
            (customer_id, plan_id, status, current_period_start, current_period_end)
        VALUES ($1, $2, 'active', $3, $4)
        RETURNING id
        """,
        customer_id,
        plan_id,
        PERIOD_START,
        PERIOD_END,
    )


async def test_new_event_creates_a_pending_charge(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    request = NewChargeRequest(
        subscription_id=subscription_id,
        amount_cents=1999,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )

    payload = {"type": "charge.created"}
    charge = await get_or_create_charge_for_event(db_conn, "evt_123", payload, request)

    assert charge.status == "pending"
    assert charge.amount_cents == 1999


async def test_replayed_event_returns_same_charge_and_does_not_duplicate(
    db_conn: asyncpg.Connection,
) -> None:
    subscription_id = await _seed_subscription(db_conn)
    request = NewChargeRequest(
        subscription_id=subscription_id,
        amount_cents=1999,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )

    payload = {"type": "charge.created"}
    first = await get_or_create_charge_for_event(db_conn, "evt_123", payload, request)
    second = await get_or_create_charge_for_event(db_conn, "evt_123", payload, request)

    assert first.id == second.id
    charge_count = await db_conn.fetchval("SELECT count(*) FROM charges")
    assert charge_count == 1
    event_count = await db_conn.fetchval(
        "SELECT count(*) FROM processed_events WHERE provider_event_id = $1", "evt_123"
    )
    assert event_count == 1


async def test_different_events_create_different_charges(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    request = NewChargeRequest(
        subscription_id=subscription_id,
        amount_cents=1999,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )

    payload = {"type": "charge.created"}
    first = await get_or_create_charge_for_event(db_conn, "evt_123", payload, request)
    second = await get_or_create_charge_for_event(db_conn, "evt_456", payload, request)

    assert first.id != second.id


async def test_duplicate_provider_event_id_rejected_at_database_level(
    db_conn: asyncpg.Connection,
) -> None:
    await db_conn.execute(
        "INSERT INTO processed_events (provider_event_id, payload) VALUES ($1, $2)",
        "evt_dupe",
        "{}",
    )

    with pytest.raises(asyncpg.UniqueViolationError):
        await db_conn.execute(
            "INSERT INTO processed_events (provider_event_id, payload) VALUES ($1, $2)",
            "evt_dupe",
            "{}",
        )
