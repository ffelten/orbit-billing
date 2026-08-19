from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.charges import Charge, ChargeStatus, IllegalChargeTransitionError
from orbit.billing.gift_cards import (
    GiftCardExpiredError,
    GiftCardNotFoundError,
    generate_gift_card_code,
    purchase_gift_card,
    redeem_gift_card_for_charge,
)

FUNDED_AT = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_START = datetime(2026, 2, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


def test_generate_gift_card_code_is_twelve_uppercase_alphanumeric_chars() -> None:
    code = generate_gift_card_code()

    assert len(code) == 12
    assert code.isalnum()
    assert code == code.upper()


async def _seed_customer(conn: asyncpg.Connection, email: str = "buyer@example.com") -> int:
    return await conn.fetchval("INSERT INTO customers (email) VALUES ($1) RETURNING id", email)


async def test_purchase_gift_card_persists_balance_and_expiry(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)

    gift_card = await purchase_gift_card(
        db_conn,
        customer_id=customer_id,
        amount_cents=5000,
        funded_at=FUNDED_AT,
    )

    assert gift_card.amount_cents == 5000
    assert gift_card.balance_cents == 5000
    assert gift_card.expires_at == FUNDED_AT + timedelta(days=365)

    stored_balance = await db_conn.fetchval(
        "SELECT balance_cents FROM gift_cards WHERE id = $1", gift_card.id
    )
    assert stored_balance == 5000


async def _seed_subscription(conn: asyncpg.Connection) -> int:
    customer_id = await _seed_customer(conn, "shopper@example.com")
    plan_id = await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) "
        "VALUES ('Pro', 2000, 'monthly') RETURNING id"
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


async def _seed_charge(
    conn: asyncpg.Connection,
    subscription_id: int,
    amount_cents: int,
    idempotency_key: str = "evt_1",
) -> Charge:
    row = await conn.fetchrow(
        """
        INSERT INTO charges
            (subscription_id, amount_cents, idempotency_key, period_start, period_end)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        subscription_id,
        amount_cents,
        idempotency_key,
        PERIOD_START,
        PERIOD_END,
    )
    return Charge(
        id=row["id"],
        subscription_id=row["subscription_id"],
        amount_cents=row["amount_cents"],
        status=ChargeStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        period_start=row["period_start"],
        period_end=row["period_end"],
    )


async def test_redeem_fully_covering_charge_settles_it(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    gift_card = await purchase_gift_card(
        db_conn, customer_id=customer_id, amount_cents=5000, funded_at=FUNDED_AT
    )
    subscription_id = await _seed_subscription(db_conn)
    charge = await _seed_charge(db_conn, subscription_id, amount_cents=5000)

    result = await redeem_gift_card_for_charge(
        db_conn, code=gift_card.code, charge=charge, redeemed_at=PERIOD_START
    )

    assert result.redeemed_cents == 5000
    assert result.gift_card.balance_cents == 0
    assert result.charge.status == ChargeStatus.SUCCEEDED

    stored_status = await db_conn.fetchval("SELECT status FROM charges WHERE id = $1", charge.id)
    assert stored_status == "succeeded"


async def test_redeem_partial_leaves_remainder_and_charge_pending(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)
    gift_card = await purchase_gift_card(
        db_conn, customer_id=customer_id, amount_cents=3000, funded_at=FUNDED_AT
    )
    subscription_id = await _seed_subscription(db_conn)
    charge = await _seed_charge(db_conn, subscription_id, amount_cents=5000)

    result = await redeem_gift_card_for_charge(
        db_conn, code=gift_card.code, charge=charge, redeemed_at=PERIOD_START
    )

    assert result.redeemed_cents == 3000
    assert result.gift_card.balance_cents == 0
    assert result.charge.status == ChargeStatus.PENDING

    stored_status = await db_conn.fetchval("SELECT status FROM charges WHERE id = $1", charge.id)
    assert stored_status == "pending"


async def test_redeem_unknown_code_raises(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    charge = await _seed_charge(db_conn, subscription_id, amount_cents=5000)

    with pytest.raises(GiftCardNotFoundError):
        await redeem_gift_card_for_charge(
            db_conn, code="NOSUCHCODE01", charge=charge, redeemed_at=PERIOD_START
        )


async def test_redeem_expired_card_raises_and_does_not_touch_balance(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)
    gift_card = await purchase_gift_card(
        db_conn, customer_id=customer_id, amount_cents=5000, funded_at=FUNDED_AT
    )
    subscription_id = await _seed_subscription(db_conn)
    charge = await _seed_charge(db_conn, subscription_id, amount_cents=5000)
    after_expiry = FUNDED_AT + timedelta(days=365)

    with pytest.raises(GiftCardExpiredError):
        await redeem_gift_card_for_charge(
            db_conn, code=gift_card.code, charge=charge, redeemed_at=after_expiry
        )

    stored_balance = await db_conn.fetchval(
        "SELECT balance_cents FROM gift_cards WHERE id = $1", gift_card.id
    )
    assert stored_balance == 5000


async def test_redeem_against_non_pending_charge_raises(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    gift_card = await purchase_gift_card(
        db_conn, customer_id=customer_id, amount_cents=5000, funded_at=FUNDED_AT
    )
    subscription_id = await _seed_subscription(db_conn)
    charge = await _seed_charge(db_conn, subscription_id, amount_cents=5000)
    succeeded_charge = charge.model_copy(update={"status": ChargeStatus.SUCCEEDED})

    with pytest.raises(IllegalChargeTransitionError):
        await redeem_gift_card_for_charge(
            db_conn, code=gift_card.code, charge=succeeded_charge, redeemed_at=PERIOD_START
        )
