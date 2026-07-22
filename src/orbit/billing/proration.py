"""Mid-period subscription plan-change proration.

Per ADR-0002, all amounts are integer cents; no floats touch this
calculation, including intermediate values.
"""

from datetime import datetime


def _round_half_up(numerator: int, denominator: int) -> int:
    """Round the non-negative fraction numerator/denominator to the nearest integer.

    Ties round away from zero. Callers apply sign separately, so both
    arguments here are always non-negative.
    """
    return (numerator * 2 + denominator) // (2 * denominator)


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
    return sign * _round_half_up(abs(numerator), total_days)


def prorated_refund_cents(
    *,
    amount_cents: int,
    period_start: datetime,
    period_end: datetime,
    refunded_at: datetime,
) -> int:
    """Refund owed for the unused portion of a charge's billing period.

    Refunds only cover unused service: `amount_cents` is scaled by the
    fraction of the period (in whole days) still unused as of
    `refunded_at`, then rounded to the nearest cent. A refund requested on
    the last day of the period prorates to zero.
    """
    total_days = (period_end - period_start).days
    if total_days <= 0:
        msg = "period_end must be at least one whole day after period_start"
        raise ValueError(msg)
    if refunded_at < period_start or refunded_at > period_end:
        msg = "refunded_at must fall within the charge's period"
        raise ValueError(msg)

    days_remaining = (period_end - refunded_at).days
    numerator = amount_cents * days_remaining
    return _round_half_up(numerator, total_days)
