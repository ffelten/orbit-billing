from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orbit.models.gift_card import GiftCard

CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_gift_card_holds_balance_in_integer_cents() -> None:
    card = GiftCard(
        id=1,
        code="ABCD-1234",
        purchaser_customer_id=1,
        face_value_cents=5000,
        balance_cents=5000,
        created_at=CREATED_AT,
    )

    assert card.balance_cents == 5000
    assert isinstance(card.balance_cents, int)


def test_gift_card_allows_balance_below_initial_amount_after_partial_redemption() -> None:
    card = GiftCard(
        id=1,
        code="ABCD-1234",
        purchaser_customer_id=1,
        face_value_cents=5000,
        balance_cents=2000,
        created_at=CREATED_AT,
    )

    assert card.balance_cents == 2000
    assert card.face_value_cents == 5000


def test_gift_card_rejects_balance_above_initial_amount() -> None:
    with pytest.raises(ValueError, match="balance_cents"):
        GiftCard(
            id=1,
            code="ABCD-1234",
            purchaser_customer_id=1,
            face_value_cents=1000,
            balance_cents=2000,
            created_at=CREATED_AT,
        )


def test_gift_card_rejects_negative_balance() -> None:
    with pytest.raises(ValidationError):
        GiftCard(
            id=1,
            code="ABCD-1234",
            purchaser_customer_id=1,
            face_value_cents=5000,
            balance_cents=-1,
            created_at=CREATED_AT,
        )


def test_gift_card_rejects_negative_initial_amount() -> None:
    with pytest.raises(ValidationError):
        GiftCard(
            id=1,
            code="ABCD-1234",
            purchaser_customer_id=1,
            face_value_cents=-1,
            balance_cents=0,
            created_at=CREATED_AT,
        )


def to_cents(dollars: float) -> int:
    """Dollars to integer cents (ADR-0002)."""
    return int(round(dollars * 100))
