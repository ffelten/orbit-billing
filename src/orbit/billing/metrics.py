"""Charge outcome counters, aggregated by day.

Incremented once per charge (not per webhook delivery) at the point a charge
settles — see the transaction in `orbit.billing.webhooks.receive_webhook`.
Redeliveries of an already-settled event return early before reaching that
transaction, so they never double-count.
"""

from dataclasses import dataclass
from datetime import date

import asyncpg

from orbit.billing.charges import ChargeStatus


@dataclass(frozen=True, slots=True)
class DailyChargeOutcomes:
    """Counts of settled charges for one day."""

    day: date
    succeeded: int
    failed: int


async def record_charge_outcome(conn: asyncpg.Connection, status: ChargeStatus) -> None:
    """Increment today's counter for `status`.

    Only `SUCCEEDED`/`FAILED` are terminal outcomes worth counting (see
    `orbit.billing.charges._ALLOWED_TRANSITIONS`); callers should only call
    this once a charge has actually settled.
    """
    await conn.execute(
        """
        INSERT INTO charge_outcome_counts (day, status, count)
        VALUES (current_date, $1, 1)
        ON CONFLICT (day, status) DO UPDATE
            SET count = charge_outcome_counts.count + 1
        """,
        status.value,
    )


async def list_charge_outcomes_by_day(conn: asyncpg.Connection) -> list[DailyChargeOutcomes]:
    """List charge outcome counts by day, most recent day first."""
    rows = await conn.fetch(
        "SELECT day, status, count FROM charge_outcome_counts ORDER BY day DESC"
    )

    by_day: dict[date, dict[str, int]] = {}
    for row in rows:
        by_day.setdefault(row["day"], {})[row["status"]] = row["count"]

    return [
        DailyChargeOutcomes(
            day=day,
            succeeded=counts.get(ChargeStatus.SUCCEEDED.value, 0),
            failed=counts.get(ChargeStatus.FAILED.value, 0),
        )
        for day, counts in sorted(by_day.items(), reverse=True)
    ]
