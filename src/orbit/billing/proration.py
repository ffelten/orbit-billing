"""Mid-period subscription plan-change proration.

Per ADR-0002, all amounts are integer cents; no floats touch this
calculation, including intermediate values.
"""

from datetime import datetime


def assert_integer_cents(value: int) -> None:
    """Reject non-integer or negative cents (ADR-0002)."""
    if value < 0 or int(value) != value:
        raise ValueError("amount must be a non-negative integer cents value")


def prorated_amount_cents(
    *,
    old_amount_cents: int,
    new_amount_cents: int,
    period_start: datetime,
    period_end: datetime,
    changed_at: datetime,
) -> int:
    """Amount owed (positive) or credited (negative) for a mid-period plan change.

    Proration is computed on whole days remaining in the current period: the
    difference between the new and old plan's amount is scaled by the
    fraction of the period (in whole days) still ahead of `changed_at`, then
    rounded to the nearest cent.

    Rounding is symmetric around zero — computed from the absolute value of
    the numerator, with the sign reapplied after — so switching to a plan
    and immediately back always nets to exactly zero, regardless of
    rounding, rather than leaking a cent to drift.
    """
    total_days = (period_end - period_start).days
    if total_days <= 0:
        msg = "period_end must be at least one whole day after period_start"
        raise ValueError(msg)
    if changed_at < period_start or changed_at > period_end:
        msg = "changed_at must fall within the current period"
        raise ValueError(msg)

    days_remaining = (period_end - changed_at).days
    numerator = (new_amount_cents - old_amount_cents) * days_remaining
    sign = 1 if numerator >= 0 else -1
    rounded = (abs(numerator) * 2 + total_days) // (2 * total_days)
    return sign * rounded
