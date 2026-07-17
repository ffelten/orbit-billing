from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.subscriptions import (
    PlanNotFoundError,
    SubscriptionNotFoundError,
    change_subscription_plan,
)

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


async def _seed_plan(conn: asyncpg.Connection, *, name: str, amount_cents: int) -> int:
    return await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) VALUES ($1, $2, 'monthly') RETURNING id",
        name,
        amount_cents,
    )


async def _seed_subscription(conn: asyncpg.Connection, plan_id: int) -> int:
    customer_id = await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", "customer@example.com"
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


async def test_upgrade_charges_prorated_difference_and_updates_plan(
    db_conn: asyncpg.Connection,
) -> None:
    old_plan_id = await _seed_plan(db_conn, name="Basic", amount_cents=1000)
    new_plan_id = await _seed_plan(db_conn, name="Pro", amount_cents=2000)
    subscription_id = await _seed_subscription(db_conn, old_plan_id)

    result = await change_subscription_plan(
        db_conn,
        subscription_id=subscription_id,
        new_plan_id=new_plan_id,
        changed_at=PERIOD_START + timedelta(days=15),
    )

    assert result.previous_plan_id == old_plan_id
    assert result.new_plan_id == new_plan_id
    assert result.prorated_amount_cents == 500

    stored_plan_id = await db_conn.fetchval(
        "SELECT plan_id FROM subscriptions WHERE id = $1", subscription_id
    )
    assert stored_plan_id == new_plan_id


async def test_downgrade_credits_prorated_difference(db_conn: asyncpg.Connection) -> None:
    old_plan_id = await _seed_plan(db_conn, name="Pro", amount_cents=2000)
    new_plan_id = await _seed_plan(db_conn, name="Basic", amount_cents=1000)
    subscription_id = await _seed_subscription(db_conn, old_plan_id)

    result = await change_subscription_plan(
        db_conn,
        subscription_id=subscription_id,
        new_plan_id=new_plan_id,
        changed_at=PERIOD_START + timedelta(days=15),
    )

    assert result.prorated_amount_cents == -500


async def test_unknown_subscription_raises(db_conn: asyncpg.Connection) -> None:
    plan_id = await _seed_plan(db_conn, name="Pro", amount_cents=2000)

    with pytest.raises(SubscriptionNotFoundError):
        await change_subscription_plan(
            db_conn,
            subscription_id=999,
            new_plan_id=plan_id,
            changed_at=PERIOD_START,
        )


async def test_unknown_plan_raises_and_does_not_change_subscription(
    db_conn: asyncpg.Connection,
) -> None:
    old_plan_id = await _seed_plan(db_conn, name="Basic", amount_cents=1000)
    subscription_id = await _seed_subscription(db_conn, old_plan_id)

    with pytest.raises(PlanNotFoundError):
        await change_subscription_plan(
            db_conn,
            subscription_id=subscription_id,
            new_plan_id=999,
            changed_at=PERIOD_START,
        )

    stored_plan_id = await db_conn.fetchval(
        "SELECT plan_id FROM subscriptions WHERE id = $1", subscription_id
    )
    assert stored_plan_id == old_plan_id
