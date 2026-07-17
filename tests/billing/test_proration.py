from datetime import UTC, datetime, timedelta

import pytest

from orbit.billing.proration import prorated_amount_cents

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


def test_upgrade_mid_period_charges_prorated_difference() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=1000,
        new_amount_cents=2000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_START + timedelta(days=15),
    )

    assert amount == 500


def test_downgrade_mid_period_credits_prorated_difference() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=2000,
        new_amount_cents=1000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_START + timedelta(days=15),
    )

    assert amount == -500


def test_change_on_last_day_of_period_prorates_one_day() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=1000,
        new_amount_cents=2000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_END - timedelta(days=1),
    )

    assert amount == 33  # round(1000 * 1 / 30)


def test_change_on_first_day_of_period_charges_full_difference() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=1000,
        new_amount_cents=2000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_START,
    )

    assert amount == 1000


def test_change_at_period_end_prorates_nothing() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=1000,
        new_amount_cents=2000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_END,
    )

    assert amount == 0


def test_rounding_is_exact_when_evenly_divisible() -> None:
    amount = prorated_amount_cents(
        old_amount_cents=1000,
        new_amount_cents=2000,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=PERIOD_START + timedelta(days=15),
    )

    # 1000 cents diff * 15/30 remaining is exactly 500, no rounding drift.
    assert amount == 500


def test_rounding_nets_to_zero_when_switching_and_switching_back() -> None:
    changed_at = PERIOD_START + timedelta(days=7)  # 23/30 remaining: not evenly divisible

    upgrade = prorated_amount_cents(
        old_amount_cents=999,
        new_amount_cents=1999,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=changed_at,
    )
    downgrade_back = prorated_amount_cents(
        old_amount_cents=1999,
        new_amount_cents=999,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        changed_at=changed_at,
    )

    assert upgrade == -downgrade_back
    assert upgrade + downgrade_back == 0


def test_changed_at_before_period_start_raises() -> None:
    with pytest.raises(ValueError, match="changed_at"):
        prorated_amount_cents(
            old_amount_cents=1000,
            new_amount_cents=2000,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            changed_at=PERIOD_START - timedelta(days=1),
        )


def test_changed_at_after_period_end_raises() -> None:
    with pytest.raises(ValueError, match="changed_at"):
        prorated_amount_cents(
            old_amount_cents=1000,
            new_amount_cents=2000,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            changed_at=PERIOD_END + timedelta(days=1),
        )


def test_zero_length_period_raises() -> None:
    with pytest.raises(ValueError, match="period_end"):
        prorated_amount_cents(
            old_amount_cents=1000,
            new_amount_cents=2000,
            period_start=PERIOD_START,
            period_end=PERIOD_START + timedelta(hours=12),
            changed_at=PERIOD_START,
        )
