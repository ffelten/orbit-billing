"""Mid-period subscription plan changes (see CONTEXT.md: Subscription)."""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from orbit.billing.proration import prorated_amount_cents


def assert_integer_cents(value: int) -> None:
    """Reject non-integer or negative cents (ADR-0002)."""
    if value < 0 or int(value) != value:
        raise ValueError("amount must be a non-negative integer cents value")


class SubscriptionNotFoundError(Exception):
    """Raised when a subscription id does not exist."""


class PlanNotFoundError(Exception):
    """Raised when a plan id does not exist."""


@dataclass(frozen=True, slots=True)
class PlanChangeResult:
    """The outcome of moving a subscription to a new plan."""

    subscription_id: int
    previous_plan_id: int
    new_plan_id: int
    prorated_amount_cents: int


async def change_subscription_plan(
    conn: asyncpg.Connection,
    *,
    subscription_id: int,
    new_plan_id: int,
    changed_at: datetime,
) -> PlanChangeResult:
    """Move `subscription_id` onto `new_plan_id`, prorating the difference.

    The subscription's current period is left unchanged — only its plan
    changes. Per ADR-0004, this reads and updates rows only; it never calls
    the payment provider. Settling the prorated amount (charging or
    crediting the customer) is the worker's job.
    """
    async with conn.transaction():
        subscription = await conn.fetchrow(
            """
            SELECT s.id, s.plan_id, s.current_period_start, s.current_period_end,
                   p.amount_cents AS old_amount_cents
            FROM subscriptions s
            JOIN plans p ON p.id = s.plan_id
            WHERE s.id = $1
            FOR UPDATE OF s
            """,
            subscription_id,
        )
        if subscription is None:
            raise SubscriptionNotFoundError(subscription_id)

        new_plan = await conn.fetchrow("SELECT amount_cents FROM plans WHERE id = $1", new_plan_id)
        if new_plan is None:
            raise PlanNotFoundError(new_plan_id)

        prorated = prorated_amount_cents(
            old_amount_cents=subscription["old_amount_cents"],
            new_amount_cents=new_plan["amount_cents"],
            period_start=subscription["current_period_start"],
            period_end=subscription["current_period_end"],
            changed_at=changed_at,
        )

        await conn.execute(
            "UPDATE subscriptions SET plan_id = $1 WHERE id = $2",
            new_plan_id,
            subscription_id,
        )

    return PlanChangeResult(
        subscription_id=subscription_id,
        previous_plan_id=subscription["plan_id"],
        new_plan_id=new_plan_id,
        prorated_amount_cents=prorated,
    )
