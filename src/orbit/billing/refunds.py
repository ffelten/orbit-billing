"""Partial refunds against a charge (see CONTEXT.md: Charge; issue #9)."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from orbit.billing.charges import Charge, ChargeStatus, transition_charge
from orbit.billing.proration import prorated_refund_cents


class ChargeNotFoundError(Exception):
    """Raised when a charge id does not exist."""


class ChargeNotRefundableError(Exception):
    """Raised when a charge is not `succeeded` or `partially_refunded`."""

    def __init__(self, charge_id: int, status: ChargeStatus) -> None:
        super().__init__(f"charge {charge_id} cannot be refunded from status {status!r}")
        self.charge_id = charge_id
        self.status = status


class RefundExceedsChargeError(Exception):
    """Raised when a refund would credit more than a charge's remaining balance."""

    def __init__(self, charge_id: int, *, refund_amount_cents: int, remaining_cents: int) -> None:
        super().__init__(
            f"refund of {refund_amount_cents} for charge {charge_id} exceeds "
            f"remaining refundable balance of {remaining_cents}"
        )
        self.charge_id = charge_id
        self.refund_amount_cents = refund_amount_cents
        self.remaining_cents = remaining_cents


@dataclass(frozen=True, slots=True)
class RefundResult:
    """The outcome of refunding part or all of a charge."""

    charge_id: int
    requested_amount_cents: int
    refunded_amount_cents: int
    total_refunded_cents: int
    charge_status: ChargeStatus


async def record_refund(
    conn: asyncpg.Connection,
    *,
    charge_id: int,
    amount_cents: int,
    refunded_at: datetime,
) -> RefundResult:
    """Refund up to `amount_cents` of `charge_id`, prorated by unused days remaining.

    Only a `succeeded` or already `partially_refunded` charge can be
    refunded — `pending` and `failed` charges never collected money, and a
    fully `refunded` charge has no balance left. `amount_cents` is the
    amount requested; the amount actually credited is prorated by the
    fraction of the charge's billing period still unused as of
    `refunded_at` (refunds only cover unused service), then capped at the
    charge's remaining refundable balance.

    Per ADR-0004, this reads and updates rows only; it never calls the
    payment provider — actually moving money is the worker's job.
    """
    if amount_cents <= 0:
        msg = "amount_cents must be positive"
        raise ValueError(msg)

    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT id, subscription_id, amount_cents, refunded_amount_cents, status,
                   idempotency_key, period_start, period_end
            FROM charges
            WHERE id = $1
            FOR UPDATE
            """,
            charge_id,
        )
        if row is None:
            raise ChargeNotFoundError(charge_id)

        charge = Charge(
            id=row["id"],
            subscription_id=row["subscription_id"],
            amount_cents=row["amount_cents"],
            status=ChargeStatus(row["status"]),
            idempotency_key=row["idempotency_key"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            refunded_amount_cents=row["refunded_amount_cents"],
        )

        if charge.status not in (ChargeStatus.SUCCEEDED, ChargeStatus.PARTIALLY_REFUNDED):
            raise ChargeNotRefundableError(charge_id, charge.status)

        refund_amount_cents = prorated_refund_cents(
            amount_cents=amount_cents,
            period_start=charge.period_start,
            period_end=charge.period_end,
            refunded_at=refunded_at,
        )
        if refund_amount_cents <= 0:
            msg = "no unused days remain in the billing period; nothing to refund"
            raise ValueError(msg)

        remaining_cents = charge.amount_cents - charge.refunded_amount_cents
        if refund_amount_cents > remaining_cents:
            raise RefundExceedsChargeError(
                charge_id,
                refund_amount_cents=refund_amount_cents,
                remaining_cents=remaining_cents,
            )

        total_refunded_cents = charge.refunded_amount_cents + refund_amount_cents
        new_status = (
            ChargeStatus.REFUNDED
            if total_refunded_cents == charge.amount_cents
            else ChargeStatus.PARTIALLY_REFUNDED
        )
        transition_charge(charge, new_status)  # raises if the transition is illegal

        await conn.execute(
            """
            INSERT INTO refunds (charge_id, requested_amount_cents, amount_cents, refunded_at)
            VALUES ($1, $2, $3, $4)
            """,
            charge_id,
            amount_cents,
            refund_amount_cents,
            refunded_at,
        )
        await conn.execute(
            """
            UPDATE charges
            SET status = $1, refunded_amount_cents = $2, updated_at = now()
            WHERE id = $3
            """,
            new_status.value,
            total_refunded_cents,
            charge_id,
        )

    return RefundResult(
        charge_id=charge_id,
        requested_amount_cents=amount_cents,
        refunded_amount_cents=refund_amount_cents,
        total_refunded_cents=total_refunded_cents,
        charge_status=new_status,
    )
