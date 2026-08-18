import pytest

from orbit.billing.coupons import UnknownCouponError, apply_coupon


def test_welcome10_takes_ten_percent_off() -> None:
    assert apply_coupon(1000, "WELCOME10") == 900


def test_annual20_takes_twenty_percent_off() -> None:
    assert apply_coupon(1000, "ANNUAL20") == 800


def test_unknown_code_raises() -> None:
    with pytest.raises(UnknownCouponError):
        apply_coupon(1000, "NOPE")
