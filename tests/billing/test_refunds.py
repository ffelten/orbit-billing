from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.charges import ChargeStatus
from orbit.billing.refunds import (
    ChargeNotFoundError,
    ChargeNotRefundableError,
    RefundExceedsChargeError,
    record_refund,
)

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


async def _seed_charge(
    conn: asyncpg.Connection,
    *,
    amount_cents: int,
    status: ChargeStatus = ChargeStatus.SUCCEEDED,
    refunded_amount_cents: int = 0,
) -> int:
    plan_id = await conn.fetchval(
        """
        INSERT INTO plans (name, amount_cents, interval)
        VALUES ('Pro', $1, 'monthly')
        RETURNING id
        """,
        amount_cents,
    )
    customer_id = await conn.fetchval(
        "INSERT INTO customers (email) VALUES ('customer@example.com') RETURNING id"
    )
    subscription_id = await conn.fetchval(
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
    return await conn.fetchval(
        """
        INSERT INTO charges
            (subscription_id, amount_cents, status, refunded_amount_cents,
             idempotency_key, period_start, period_end)
        VALUES ($1, $2, $3, $4, 'evt_1', $5, $6)
        RETURNING id
        """,
        subscription_id,
        amount_cents,
        status.value,
        refunded_amount_cents,
        PERIOD_START,
        PERIOD_END,
    )


async def test_refund_mid_period_prorates_and_partially_refunds(
    db_conn: asyncpg.Connection,
) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)

    result = await record_refund(
        db_conn,
        charge_id=charge_id,
        amount_cents=3000,
        refunded_at=PERIOD_START + timedelta(days=20),
    )

    assert result.requested_amount_cents == 3000
    assert result.refunded_amount_cents == 1000  # 10/30 days remaining
    assert result.total_refunded_cents == 1000
    assert result.charge_status == ChargeStatus.PARTIALLY_REFUNDED

    row = await db_conn.fetchrow(
        "SELECT status, refunded_amount_cents FROM charges WHERE id = $1", charge_id
    )
    assert row["status"] == "partially_refunded"
    assert row["refunded_amount_cents"] == 1000

    refund_row = await db_conn.fetchrow("SELECT * FROM refunds WHERE charge_id = $1", charge_id)
    assert refund_row["requested_amount_cents"] == 3000
    assert refund_row["amount_cents"] == 1000


async def test_refund_on_first_day_fully_refunds_charge(db_conn: asyncpg.Connection) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)

    result = await record_refund(
        db_conn,
        charge_id=charge_id,
        amount_cents=3000,
        refunded_at=PERIOD_START,
    )

    assert result.refunded_amount_cents == 3000
    assert result.charge_status == ChargeStatus.REFUNDED

    status = await db_conn.fetchval("SELECT status FROM charges WHERE id = $1", charge_id)
    assert status == "refunded"


async def test_second_partial_refund_accumulates(db_conn: asyncpg.Connection) -> None:
    charge_id = await _seed_charge(
        db_conn,
        amount_cents=3000,
        status=ChargeStatus.PARTIALLY_REFUNDED,
        refunded_amount_cents=1000,
    )

    result = await record_refund(
        db_conn,
        charge_id=charge_id,
        amount_cents=2000,
        refunded_at=PERIOD_START,
    )

    assert result.refunded_amount_cents == 2000
    assert result.total_refunded_cents == 3000
    assert result.charge_status == ChargeStatus.REFUNDED


async def test_refund_exceeding_remaining_balance_raises(db_conn: asyncpg.Connection) -> None:
    charge_id = await _seed_charge(
        db_conn,
        amount_cents=3000,
        status=ChargeStatus.PARTIALLY_REFUNDED,
        refunded_amount_cents=1000,
    )

    with pytest.raises(RefundExceedsChargeError):
        await record_refund(
            db_conn,
            charge_id=charge_id,
            amount_cents=2500,
            refunded_at=PERIOD_START,
        )

    row = await db_conn.fetchrow(
        "SELECT status, refunded_amount_cents FROM charges WHERE id = $1", charge_id
    )
    assert row["status"] == "partially_refunded"
    assert row["refunded_amount_cents"] == 1000


@pytest.mark.parametrize(
    "status", [ChargeStatus.PENDING, ChargeStatus.FAILED, ChargeStatus.REFUNDED]
)
async def test_refunding_a_non_refundable_charge_raises(
    db_conn: asyncpg.Connection, status: ChargeStatus
) -> None:
    refunded_amount_cents = 3000 if status == ChargeStatus.REFUNDED else 0
    charge_id = await _seed_charge(
        db_conn,
        amount_cents=3000,
        status=status,
        refunded_amount_cents=refunded_amount_cents,
    )

    with pytest.raises(ChargeNotRefundableError):
        await record_refund(
            db_conn,
            charge_id=charge_id,
            amount_cents=1000,
            refunded_at=PERIOD_START,
        )


async def test_unknown_charge_raises(db_conn: asyncpg.Connection) -> None:
    with pytest.raises(ChargeNotFoundError):
        await record_refund(
            db_conn,
            charge_id=999,
            amount_cents=1000,
            refunded_at=PERIOD_START,
        )


async def test_non_positive_amount_raises(db_conn: asyncpg.Connection) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)

    with pytest.raises(ValueError, match="amount_cents"):
        await record_refund(
            db_conn,
            charge_id=charge_id,
            amount_cents=0,
            refunded_at=PERIOD_START,
        )


async def test_refund_at_period_end_raises_nothing_to_refund(
    db_conn: asyncpg.Connection,
) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)

    with pytest.raises(ValueError, match="nothing to refund"):
        await record_refund(
            db_conn,
            charge_id=charge_id,
            amount_cents=3000,
            refunded_at=PERIOD_END,
        )
