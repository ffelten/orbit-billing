"""Gift card purchase and redemption (see docs/prd/gift-cards.md, ADR-0005)."""

import json
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg

from orbit.billing.charges import (
    Charge,
    ChargeStatus,
    IllegalChargeTransitionError,
    transition_charge,
)
from orbit.billing.metrics import record_charge_outcome
from orbit.models.gift_card import GiftCard

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 12
_EXPIRY = timedelta(days=365)


class GiftCardNotFoundError(Exception):
    """Raised when a gift card code does not match a known card."""


class GiftCardExpiredError(Exception):
    """Raised when redemption is attempted against an expired gift card (ADR-0005)."""


class CustomerNotFoundError(Exception):
    """Raised when a customer id does not exist."""


@dataclass(frozen=True, slots=True)
class RedemptionResult:
    """The outcome of redeeming a gift card against a charge."""

    charge: Charge
    gift_card: GiftCard
    redeemed_cents: int


def generate_gift_card_code() -> str:
    """Generate a 12-character uppercase alphanumeric gift card code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def purchase_gift_card(
    conn: asyncpg.Connection,
    *,
    customer_id: int,
    face_value_cents: int,
    funded_at: datetime,
) -> GiftCard:
    """Sell a gift card for `face_value_cents`, funded now and expiring in twelve months (ADR-0005).

    The code is returned to the caller to display at checkout; it is not
    emailed (see `orbit.notify.templates.gift_card_purchased` if that
    changes).
    """
    code = generate_gift_card_code()
    expires_at = funded_at + _EXPIRY

    row = await conn.fetchrow(
        """
        INSERT INTO gift_cards
            (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        customer_id,
        code,
        face_value_cents,
        face_value_cents,
        funded_at,
        expires_at,
    )
    return _gift_card_from_row(row)


async def issue_gift_cards_bulk(
    conn: asyncpg.Connection,
    *,
    customer_id: int,
    count: int,
    face_value_cents: int,
    funded_at: datetime,
) -> list[GiftCard]:
    """Issue `count` gift cards of `face_value_cents`, all owned by `customer_id`.

    For corporate clients buying gift cards in bulk to distribute themselves
    (see docs/prd/gift-cards.md and the admin bulk-issuance endpoint); every
    card gets its own unique code but shares the purchaser's `customer_id` —
    there is no unassigned-card concept. All inserts happen in a single
    transaction, so a failure partway through issues none of them.
    """
    async with conn.transaction():
        customer = await conn.fetchrow("SELECT id FROM customers WHERE id = $1", customer_id)
        if customer is None:
            raise CustomerNotFoundError(customer_id)

        expires_at = funded_at + _EXPIRY
        gift_cards = []
        for _ in range(count):
            row = await conn.fetchrow(
                """
                INSERT INTO gift_cards
                    (customer_id, code, face_value_cents, balance_cents, funded_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                customer_id,
                generate_gift_card_code(),
                face_value_cents,
                face_value_cents,
                funded_at,
                expires_at,
            )
            gift_cards.append(_gift_card_from_row(row))

    return gift_cards


async def redeem_gift_card_for_charge(
    conn: asyncpg.Connection,
    *,
    code: str,
    charge: Charge,
    redeemed_at: datetime,
) -> RedemptionResult:
    """Apply a gift card's balance to `charge`, up to the balance or the amount owed.

    Partial redemption is allowed — any remainder stays on the card. Fully
    covering the charge settles it through the existing charges flow
    (`transition_charge` + persisted status + outcome metrics, mirroring
    `orbit.billing.webhooks.receive_webhook`); a shortfall leaves the charge
    pending. Refuses an expired card with an explicit error rather than
    silently treating it as zero balance (ADR-0005).
    """
    if charge.status is not ChargeStatus.PENDING:
        raise IllegalChargeTransitionError(charge.status, ChargeStatus.SUCCEEDED)

    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM gift_cards WHERE code = $1 FOR UPDATE", code)
        if row is None:
            raise GiftCardNotFoundError(code)

        gift_card = _gift_card_from_row(row)
        if redeemed_at >= gift_card.expires_at:
            raise GiftCardExpiredError(code)

        redeemed_cents = min(gift_card.balance_cents, charge.amount_cents)
        updated_row = await conn.fetchrow(
            "UPDATE gift_cards SET balance_cents = balance_cents - $1 WHERE id = $2 RETURNING *",
            redeemed_cents,
            gift_card.id,
        )
        updated_gift_card = _gift_card_from_row(updated_row)

        updated_charge = charge
        if redeemed_cents == charge.amount_cents:
            updated_charge = transition_charge(charge, ChargeStatus.SUCCEEDED)
            await conn.execute(
                "UPDATE charges SET status = $1, updated_at = now() WHERE id = $2",
                updated_charge.status.value,
                updated_charge.id,
            )
            await record_charge_outcome(conn, updated_charge.status)

    return RedemptionResult(
        charge=updated_charge, gift_card=updated_gift_card, redeemed_cents=redeemed_cents
    )


def _gift_card_from_row(row: asyncpg.Record) -> GiftCard:
    return GiftCard(
        id=row["id"],
        customer_id=row["customer_id"],
        code=row["code"],
        face_value_cents=row["face_value_cents"],
        balance_cents=row["balance_cents"],
        funded_at=row["funded_at"],
        expires_at=row["expires_at"],
    )
