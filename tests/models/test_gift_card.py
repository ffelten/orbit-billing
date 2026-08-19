from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from pydantic import ValidationError

from orbit.models.gift_card import GiftCard

FUNDED_AT = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRES_AT = FUNDED_AT + timedelta(days=365)


async def _seed_customer(conn: asyncpg.Connection) -> int:
    return await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", "buyer@example.com"
    )


def test_gift_card_holds_balance_in_integer_cents() -> None:
    gift_card = GiftCard(
        id=1,
        customer_id=1,
        code="ABCD-1234",
        face_value_cents=5000,
        balance_cents=5000,
        funded_at=FUNDED_AT,
        expires_at=EXPIRES_AT,
    )

    assert gift_card.face_value_cents == 5000
    assert isinstance(gift_card.balance_cents, int)


def test_gift_card_rejects_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        GiftCard(
            id=1,
            customer_id=1,
            code="ABCD-1234",
            face_value_cents=0,
            balance_cents=0,
            funded_at=FUNDED_AT,
            expires_at=EXPIRES_AT,
        )


async def test_gift_cards_table_accepts_a_valid_row(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)

    gift_card_id = await db_conn.fetchval(
        """
        INSERT INTO gift_cards
            (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        customer_id,
        "ABCD-1234",
        5000,
        5000,
        FUNDED_AT,
        EXPIRES_AT,
    )

    stored_balance = await db_conn.fetchval(
        "SELECT balance_cents FROM gift_cards WHERE id = $1", gift_card_id
    )
    assert stored_balance == 5000


async def test_gift_cards_table_rejects_balance_above_amount(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)

    with pytest.raises(asyncpg.CheckViolationError):
        await db_conn.execute(
            """
            INSERT INTO gift_cards
                (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            customer_id,
            "ABCD-1234",
            5000,
            5001,
            FUNDED_AT,
            EXPIRES_AT,
        )


async def test_gift_cards_table_rejects_duplicate_code(db_conn: asyncpg.Connection) -> None:
    customer_id = await _seed_customer(db_conn)
    await db_conn.execute(
        """
        INSERT INTO gift_cards
            (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        customer_id,
        "ABCD-1234",
        5000,
        5000,
        FUNDED_AT,
        EXPIRES_AT,
    )

    with pytest.raises(asyncpg.UniqueViolationError):
        await db_conn.execute(
            """
            INSERT INTO gift_cards
                (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            customer_id,
            "ABCD-1234",
            2500,
            2500,
            FUNDED_AT,
            EXPIRES_AT,
        )


def test_gift_card_rejects_expiry_before_funding() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        GiftCard(
            id=1,
            customer_id=1,
            code="ABCD-1234",
            face_value_cents=5000,
            balance_cents=5000,
            funded_at=FUNDED_AT,
            expires_at=FUNDED_AT - timedelta(days=1),
        )


def test_gift_card_rejects_balance_above_amount() -> None:
    with pytest.raises(ValueError, match="balance_cents"):
        GiftCard(
            id=1,
            customer_id=1,
            code="ABCD-1234",
            face_value_cents=5000,
            balance_cents=5001,
            funded_at=FUNDED_AT,
            expires_at=EXPIRES_AT,
        )
