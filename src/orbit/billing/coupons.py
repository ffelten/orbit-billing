"""Legacy percent-off coupon codes.

This module predates plans and subscriptions — it was Orbit's only discount
mechanism before pricing moved to the plan model. It is slated for removal
in favor of gift cards (see `docs/prd/gift-cards.md`).
"""

_PERCENT_OFF: dict[str, int] = {
    "WELCOME10": 10,
    "ANNUAL20": 20,
}


class UnknownCouponError(Exception):
    """Raised when a coupon code does not match a known code."""


def apply_coupon(amount_cents: int, code: str) -> int:
    """Apply a percent-off coupon to an amount, in integer cents."""
    percent_off = _PERCENT_OFF.get(code)
    if percent_off is None:
        msg = f"unknown coupon code: {code!r}"
        raise UnknownCouponError(msg)
    return amount_cents - (amount_cents * percent_off) // 100
