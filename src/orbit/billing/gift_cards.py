"""Gift card purchase and redemption (see CONTEXT.md: Gift card, docs/prd/gift-cards.md)."""

import secrets
import string

import asyncpg

from orbit.billing.charges import Charge, ChargeStatus
from orbit.models.gift_card import GiftCard

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 12


class ChargeNotPendingError(Exception):
    """Raised when redemption is attempted against a charge that isn't pending."""

    def __init__(self, charge_id: int, status: ChargeStatus) -> None:
        super().__init__(f"charge {charge_id} is not pending (status: {status.value!r})")


class InsufficientGiftCardBalanceError(Exception):
    """Raised when a redemption amount exceeds the gift card's remaining balance."""

    def __init__(self, gift_card_id: int, requested_cents: int, balance_cents: int) -> None:
        super().__init__(
            f"gift card {gift_card_id} has balance {balance_cents} cents, "
            f"cannot redeem {requested_cents} cents"
        )


class GiftCardNotFoundError(Exception):
    """Raised when a gift card code does not exist."""

    def __init__(self, code: str) -> None:
        super().__init__(f"no gift card found for code {code!r}")


class ChargeNotFoundError(Exception):
    """Raised when a charge id does not exist."""

    def __init__(self, charge_id: int) -> None:
        super().__init__(f"no charge found for id {charge_id}")


class RedemptionExceedsChargeAmountError(Exception):
    """Raised when a redemption amount exceeds the charge's owed amount."""

    def __init__(self, charge_id: int, requested_cents: int, amount_cents: int) -> None:
        super().__init__(
            f"charge {charge_id} owes {amount_cents} cents, cannot redeem {requested_cents} cents"
        )


def generate_gift_card_code() -> str:
    """Generate a 12-character uppercase alphanumeric gift card code.

    Uses `secrets` rather than `random`: a code is a bearer credential
    redeemable for money, so it must not be guessable.
    """
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def redeem_gift_card_against_charge(
    gift_card: GiftCard, charge: Charge, amount_cents: int
) -> tuple[GiftCard, Charge]:
    """Apply `amount_cents` of `gift_card`'s balance against `charge`.

    Partial redemption is allowed; the remainder stays on the card (PRD).
    Returns new `(gift_card, charge)` instances with the balance and the
    charge's owed amount both reduced by `amount_cents`; neither input is
    mutated.

    Raises if `charge` is not pending, or if `amount_cents` exceeds the
    card's balance or the charge's owed amount — redemption never silently
    clamps to what's available.
    """
    if charge.status is not ChargeStatus.PENDING:
        raise ChargeNotPendingError(charge.id, charge.status)
    if amount_cents > gift_card.balance_cents:
        raise InsufficientGiftCardBalanceError(gift_card.id, amount_cents, gift_card.balance_cents)
    if amount_cents > charge.amount_cents:
        raise RedemptionExceedsChargeAmountError(charge.id, amount_cents, charge.amount_cents)

    updated_card = gift_card.model_copy(
        update={"balance_cents": gift_card.balance_cents - amount_cents}
    )
    updated_charge = charge.model_copy(update={"amount_cents": charge.amount_cents - amount_cents})
    return updated_card, updated_charge


async def purchase_gift_card(
    conn: asyncpg.Connection, *, purchaser_customer_id: int, amount_cents: int
) -> GiftCard:
    """Sell a gift card for `amount_cents`; the code is shown on screen after checkout.

    The code is generated here rather than left to the database so it can be
    produced with `secrets` (cryptographically unguessable) instead of a
    sequence or a weaker default.
    """
    code = generate_gift_card_code()
    row = await conn.fetchrow(
        """
        INSERT INTO gift_cards (code, purchaser_customer_id, initial_amount_cents, balance_cents)
        VALUES ($1, $2, $3, $3)
        RETURNING *
        """,
        code,
        purchaser_customer_id,
        amount_cents,
    )
    return _gift_card_from_row(row)


def _gift_card_from_row(row: asyncpg.Record) -> GiftCard:
    return GiftCard(
        id=row["id"],
        code=row["code"],
        purchaser_customer_id=row["purchaser_customer_id"],
        initial_amount_cents=row["initial_amount_cents"],
        balance_cents=row["balance_cents"],
        created_at=row["created_at"],
    )


def _charge_from_row(row: asyncpg.Record) -> Charge:
    return Charge(
        id=row["id"],
        subscription_id=row["subscription_id"],
        amount_cents=row["amount_cents"],
        status=ChargeStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        period_start=row["period_start"],
        period_end=row["period_end"],
    )


async def redeem_gift_card(
    conn: asyncpg.Connection, *, code: str, charge_id: int, amount_cents: int
) -> tuple[GiftCard, Charge]:
    """Redeem `amount_cents` of the gift card identified by `code` against `charge_id`.

    Loads both rows, applies `redeem_gift_card_against_charge`, and persists
    the reduced balance and charge amount in one transaction.
    """
    async with conn.transaction():
        card_row = await conn.fetchrow(
            "SELECT * FROM gift_cards WHERE code = $1 FOR UPDATE", code
        )
        if card_row is None:
            raise GiftCardNotFoundError(code)

        charge_row = await conn.fetchrow(
            "SELECT * FROM charges WHERE id = $1 FOR UPDATE", charge_id
        )
        if charge_row is None:
            raise ChargeNotFoundError(charge_id)

        gift_card = _gift_card_from_row(card_row)
        charge = _charge_from_row(charge_row)

        updated_card, updated_charge = redeem_gift_card_against_charge(
            gift_card, charge, amount_cents
        )

        await conn.execute(
            "UPDATE gift_cards SET balance_cents = $1 WHERE id = $2",
            updated_card.balance_cents,
            updated_card.id,
        )
        await conn.execute(
            "UPDATE charges SET amount_cents = $1, updated_at = now() WHERE id = $2",
            updated_charge.amount_cents,
            updated_charge.id,
        )

    return updated_card, updated_charge
