from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.summary import CustomerNotFoundError, get_billing_summary

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


async def _seed_customer(conn: asyncpg.Connection, *, email: str = "customer@example.com") -> int:
    return await conn.fetchval("INSERT INTO customers (email) VALUES ($1) RETURNING id", email)


async def _seed_plan(
    conn: asyncpg.Connection, *, name: str, amount_cents: int, interval: str = "monthly"
) -> int:
    return await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) VALUES ($1, $2, $3) RETURNING id",
        name,
        amount_cents,
        interval,
    )


async def _seed_subscription(
    conn: asyncpg.Connection, *, customer_id: int, plan_id: int, status: str = "active"
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO subscriptions
            (customer_id, plan_id, status, current_period_start, current_period_end)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        customer_id,
        plan_id,
        status,
        PERIOD_START,
        PERIOD_END,
    )


async def _seed_charge(  # noqa: PLR0913 -- test helper, one kwarg per column being seeded
    conn: asyncpg.Connection,
    *,
    subscription_id: int,
    amount_cents: int,
    status: str,
    created_at: datetime,
    idempotency_key: str,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO charges
            (subscription_id, amount_cents, status, idempotency_key,
             period_start, period_end, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        subscription_id,
        amount_cents,
        status,
        idempotency_key,
        PERIOD_START,
        PERIOD_END,
        created_at,
    )


async def test_unknown_customer_raises(db_conn: asyncpg.Connection) -> None:
    with pytest.raises(CustomerNotFoundError):
        await get_billing_summary(db_conn, customer_id=999)


async def test_summary_includes_active_subscription(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    plan_id = await _seed_plan(db_conn, name="Pro Monthly", amount_cents=1999)
    await _seed_subscription(db_conn, customer_id=customer_id, plan_id=plan_id)

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.active_subscription is not None
    assert summary.active_subscription.plan_name == "Pro Monthly"
    assert summary.active_subscription.amount_cents == 1999
    assert summary.active_subscription.interval == "monthly"


async def test_summary_has_no_active_subscription_when_none_exists(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.active_subscription is None


async def test_summary_ignores_canceled_subscription(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    plan_id = await _seed_plan(db_conn, name="Pro Monthly", amount_cents=1999)
    await _seed_subscription(db_conn, customer_id=customer_id, plan_id=plan_id, status="canceled")

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.active_subscription is None


async def test_summary_returns_last_10_charges_newest_first(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    plan_id = await _seed_plan(db_conn, name="Pro Monthly", amount_cents=1999)
    subscription_id = await _seed_subscription(db_conn, customer_id=customer_id, plan_id=plan_id)

    for i in range(12):
        await _seed_charge(
            db_conn,
            subscription_id=subscription_id,
            amount_cents=1000 + i,
            status="succeeded",
            created_at=PERIOD_START + timedelta(hours=i),
            idempotency_key=f"evt_{i}",
        )

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert len(summary.recent_charges) == 10
    amounts = [charge.amount_cents for charge in summary.recent_charges]
    assert amounts == sorted(amounts, reverse=True)
    assert amounts[0] == 1011  # the most recently created charge
    assert amounts[-1] == 1002  # the 10th most recent, i.e. charge index 2


async def test_summary_total_charged_counts_only_succeeded_charges(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)
    plan_id = await _seed_plan(db_conn, name="Pro Monthly", amount_cents=1999)
    subscription_id = await _seed_subscription(db_conn, customer_id=customer_id, plan_id=plan_id)

    await _seed_charge(
        db_conn,
        subscription_id=subscription_id,
        amount_cents=1999,
        status="succeeded",
        created_at=PERIOD_START,
        idempotency_key="evt_succeeded_1",
    )
    await _seed_charge(
        db_conn,
        subscription_id=subscription_id,
        amount_cents=1999,
        status="succeeded",
        created_at=PERIOD_START + timedelta(hours=1),
        idempotency_key="evt_succeeded_2",
    )
    await _seed_charge(
        db_conn,
        subscription_id=subscription_id,
        amount_cents=1999,
        status="pending",
        created_at=PERIOD_START + timedelta(hours=2),
        idempotency_key="evt_pending",
    )
    await _seed_charge(
        db_conn,
        subscription_id=subscription_id,
        amount_cents=1999,
        status="failed",
        created_at=PERIOD_START + timedelta(hours=3),
        idempotency_key="evt_failed",
    )

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.total_charged_cents == 3998


async def test_summary_has_zero_total_when_no_charges(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.total_charged_cents == 0
    assert summary.recent_charges == []


async def test_summary_scopes_data_to_the_given_customer(db_conn: asyncpg.Connection) -> None:
    plan_id = await _seed_plan(db_conn, name="Pro Monthly", amount_cents=1999)

    customer_id = await _seed_customer(db_conn, email="customer@example.com")
    subscription_id = await _seed_subscription(db_conn, customer_id=customer_id, plan_id=plan_id)
    await _seed_charge(
        db_conn,
        subscription_id=subscription_id,
        amount_cents=1999,
        status="succeeded",
        created_at=PERIOD_START,
        idempotency_key="evt_customer",
    )

    other_customer_id = await _seed_customer(db_conn, email="other@example.com")
    other_subscription_id = await _seed_subscription(
        db_conn, customer_id=other_customer_id, plan_id=plan_id
    )
    await _seed_charge(
        db_conn,
        subscription_id=other_subscription_id,
        amount_cents=5000,
        status="succeeded",
        created_at=PERIOD_START,
        idempotency_key="evt_other_customer",
    )

    summary = await get_billing_summary(db_conn, customer_id=customer_id)

    assert summary.total_charged_cents == 1999
    assert len(summary.recent_charges) == 1
