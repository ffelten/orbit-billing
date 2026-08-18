import re
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.charges import Charge, ChargeStatus
from orbit.billing.gift_cards import (
    ChargeNotFoundError,
    ChargeNotPendingError,
    GiftCardNotFoundError,
    InsufficientGiftCardBalanceError,
    RedemptionExceedsChargeAmountError,
    bulk_issue_gift_cards,
    generate_gift_card_code,
    purchase_gift_card,
    redeem_gift_card,
    redeem_gift_card_against_charge,
)
from orbit.models.gift_card import GiftCard

_CODE_PATTERN = re.compile(r"^[A-Z0-9]{12}$")

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
_PERIOD_END = _PERIOD_START + timedelta(days=30)


def _gift_card(*, balance_cents: int, face_value_cents: int = 5000) -> GiftCard:
    return GiftCard(
        id=1,
        code="ABCD1234EFGH",
        purchaser_customer_id=1,
        face_value_cents=face_value_cents,
        balance_cents=balance_cents,
        created_at=_CREATED_AT,
    )


def _charge(*, amount_cents: int, status: ChargeStatus = ChargeStatus.PENDING) -> Charge:
    return Charge(
        id=1,
        subscription_id=1,
        amount_cents=amount_cents,
        status=status,
        idempotency_key="evt_1",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )


async def _seed_customer(conn: asyncpg.Connection, *, email: str = "buyer@example.com") -> int:
    return await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", email
    )


async def _seed_plan(conn: asyncpg.Connection, *, amount_cents: int = 1000) -> int:
    return await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) VALUES ('Basic', $1, 'monthly') "
        "RETURNING id",
        amount_cents,
    )


async def _seed_charge(
    conn: asyncpg.Connection,
    *,
    amount_cents: int,
    status: str = "pending",
    idempotency_key: str = "evt_1",
) -> int:
    customer_id = await _seed_customer(conn, email=f"{idempotency_key}@example.com")
    plan_id = await _seed_plan(conn)
    subscription_id = await conn.fetchval(
        """
        INSERT INTO subscriptions
            (customer_id, plan_id, status, current_period_start, current_period_end)
        VALUES ($1, $2, 'active', $3, $4)
        RETURNING id
        """,
        customer_id,
        plan_id,
        _PERIOD_START,
        _PERIOD_END,
    )
    return await conn.fetchval(
        """
        INSERT INTO charges (subscription_id, amount_cents, status, idempotency_key,
                              period_start, period_end)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        subscription_id,
        amount_cents,
        status,
        idempotency_key,
        _PERIOD_START,
        _PERIOD_END,
    )


async def _seed_gift_card(conn: asyncpg.Connection, *, balance_cents: int) -> str:
    customer_id = await _seed_customer(conn, email=f"purchaser-{balance_cents}@example.com")
    code = generate_gift_card_code()
    await conn.execute(
        """
        INSERT INTO gift_cards (code, purchaser_customer_id, face_value_cents, balance_cents)
        VALUES ($1, $2, $3, $3)
        """,
        code,
        customer_id,
        balance_cents,
    )
    return code


async def test_redeem_gift_card_persists_reduced_balance_and_charge_amount(
    db_conn: asyncpg.Connection,
) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)
    code = await _seed_gift_card(db_conn, balance_cents=5000)

    updated_card, updated_charge = await redeem_gift_card(
        db_conn, code=code, charge_id=charge_id, amount_cents=2000
    )

    assert updated_card.balance_cents == 3000
    assert updated_charge.amount_cents == 1000

    stored_balance = await db_conn.fetchval(
        "SELECT balance_cents FROM gift_cards WHERE code = $1", code
    )
    stored_charge_amount = await db_conn.fetchval(
        "SELECT amount_cents FROM charges WHERE id = $1", charge_id
    )
    assert stored_balance == 3000
    assert stored_charge_amount == 1000


async def test_redeem_gift_card_unknown_code_raises(db_conn: asyncpg.Connection) -> None:
    charge_id = await _seed_charge(db_conn, amount_cents=3000)

    with pytest.raises(GiftCardNotFoundError):
        await redeem_gift_card(db_conn, code="NOSUCHCODE12", charge_id=charge_id, amount_cents=1000)


async def test_redeem_gift_card_unknown_charge_raises(db_conn: asyncpg.Connection) -> None:
    code = await _seed_gift_card(db_conn, balance_cents=5000)

    with pytest.raises(ChargeNotFoundError):
        await redeem_gift_card(db_conn, code=code, charge_id=999, amount_cents=1000)


async def test_purchase_gift_card_inserts_a_row_with_full_balance(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)

    gift_card = await purchase_gift_card(
        db_conn, purchaser_customer_id=customer_id, amount_cents=5000
    )

    assert gift_card.purchaser_customer_id == customer_id
    assert gift_card.face_value_cents == 5000
    assert gift_card.balance_cents == 5000
    assert _CODE_PATTERN.match(gift_card.code)

    stored_balance = await db_conn.fetchval(
        "SELECT balance_cents FROM gift_cards WHERE id = $1", gift_card.id
    )
    assert stored_balance == 5000


async def test_bulk_issue_gift_cards_creates_count_cards_of_the_given_amount(
    db_conn: asyncpg.Connection,
) -> None:
    customer_id = await _seed_customer(db_conn)

    gift_cards = await bulk_issue_gift_cards(
        db_conn, purchaser_customer_id=customer_id, amount_cents=5000, count=3
    )

    assert len(gift_cards) == 3
    assert {gc.face_value_cents for gc in gift_cards} == {5000}
    assert {gc.balance_cents for gc in gift_cards} == {5000}
    assert len({gc.code for gc in gift_cards}) == 3

    stored_count = await db_conn.fetchval(
        "SELECT count(*) FROM gift_cards WHERE purchaser_customer_id = $1", customer_id
    )
    assert stored_count == 3


def test_generate_gift_card_code_is_twelve_uppercase_alphanumeric_chars() -> None:
    code = generate_gift_card_code()

    assert _CODE_PATTERN.match(code)


def test_generate_gift_card_code_is_not_constant() -> None:
    codes = {generate_gift_card_code() for _ in range(50)}

    assert len(codes) == 50


def test_partial_redemption_reduces_balance_and_charge_amount_and_leaves_remainder() -> None:
    gift_card = _gift_card(balance_cents=5000)
    charge = _charge(amount_cents=3000)

    updated_card, updated_charge = redeem_gift_card_against_charge(gift_card, charge, 2000)

    assert updated_card.balance_cents == 3000
    assert updated_charge.amount_cents == 1000


def test_redemption_does_not_mutate_original_gift_card_or_charge() -> None:
    gift_card = _gift_card(balance_cents=5000)
    charge = _charge(amount_cents=3000)

    redeem_gift_card_against_charge(gift_card, charge, 2000)

    assert gift_card.balance_cents == 5000
    assert charge.amount_cents == 3000


def test_full_redemption_zeroes_gift_card_balance() -> None:
    gift_card = _gift_card(balance_cents=5000)
    charge = _charge(amount_cents=5000)

    updated_card, updated_charge = redeem_gift_card_against_charge(gift_card, charge, 5000)

    assert updated_card.balance_cents == 0
    assert updated_charge.amount_cents == 0


def test_redemption_above_gift_card_balance_raises() -> None:
    gift_card = _gift_card(balance_cents=1000)
    charge = _charge(amount_cents=5000)

    with pytest.raises(InsufficientGiftCardBalanceError):
        redeem_gift_card_against_charge(gift_card, charge, 2000)


def test_redemption_above_charge_amount_raises() -> None:
    gift_card = _gift_card(balance_cents=5000)
    charge = _charge(amount_cents=1000)

    with pytest.raises(RedemptionExceedsChargeAmountError):
        redeem_gift_card_against_charge(gift_card, charge, 2000)


@pytest.mark.parametrize("status", [ChargeStatus.SUCCEEDED, ChargeStatus.FAILED])
def test_redemption_against_non_pending_charge_raises(status: ChargeStatus) -> None:
    gift_card = _gift_card(balance_cents=5000)
    charge = _charge(amount_cents=3000, status=status)

    with pytest.raises(ChargeNotPendingError):
        redeem_gift_card_against_charge(gift_card, charge, 1000)
