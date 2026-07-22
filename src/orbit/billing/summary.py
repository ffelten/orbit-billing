"""Customer billing summary: active subscription, recent charges, total charged."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

_RECENT_CHARGES_LIMIT = 10


class CustomerNotFoundError(Exception):
    """Raised when a customer id does not exist."""


@dataclass(frozen=True, slots=True)
class ActiveSubscriptionSummary:
    plan_name: str
    amount_cents: int
    interval: str


@dataclass(frozen=True, slots=True)
class ChargeSummary:
    id: int
    amount_cents: int
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BillingSummary:
    customer_id: int
    active_subscription: ActiveSubscriptionSummary | None
    recent_charges: list[ChargeSummary]
    total_charged_cents: int


async def get_billing_summary(conn: asyncpg.Connection, *, customer_id: int) -> BillingSummary:
    """Build the billing summary for `customer_id`.

    `total_charged_cents` counts only `succeeded` charges — pending and
    failed charges were never actually collected from the customer.
    """
    customer = await conn.fetchrow("SELECT id FROM customers WHERE id = $1", customer_id)
    if customer is None:
        raise CustomerNotFoundError(customer_id)

    subscription_row = await conn.fetchrow(
        """
        SELECT p.name, p.amount_cents, p.interval
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.customer_id = $1 AND s.status = 'active'
        ORDER BY s.id DESC
        LIMIT 1
        """,
        customer_id,
    )
    active_subscription = (
        ActiveSubscriptionSummary(
            plan_name=subscription_row["name"],
            amount_cents=subscription_row["amount_cents"],
            interval=subscription_row["interval"],
        )
        if subscription_row is not None
        else None
    )

    charge_rows = await conn.fetch(
        """
        SELECT c.id, c.amount_cents, c.status, c.created_at
        FROM charges c
        JOIN subscriptions s ON s.id = c.subscription_id
        WHERE s.customer_id = $1
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT $2
        """,
        customer_id,
        _RECENT_CHARGES_LIMIT,
    )
    recent_charges = [
        ChargeSummary(
            id=row["id"],
            amount_cents=row["amount_cents"],
            status=row["status"],
            created_at=row["created_at"],
        )
        for row in charge_rows
    ]

    total_charged_cents = await conn.fetchval(
        """
        SELECT COALESCE(SUM(c.amount_cents), 0)
        FROM charges c
        JOIN subscriptions s ON s.id = c.subscription_id
        WHERE s.customer_id = $1 AND c.status = 'succeeded'
        """,
        customer_id,
    )

    return BillingSummary(
        customer_id=customer_id,
        active_subscription=active_subscription,
        recent_charges=recent_charges,
        total_charged_cents=total_charged_cents,
    )
