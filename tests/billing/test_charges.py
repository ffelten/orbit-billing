from datetime import UTC, datetime, timedelta

import pytest

from orbit.billing.charges import (
    Charge,
    ChargeStatus,
    IllegalChargeTransitionError,
    transition_charge,
)

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


def _pending_charge() -> Charge:
    return Charge(
        id=1,
        subscription_id=1,
        amount_cents=1999,
        idempotency_key="evt_1",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )


def test_charge_starts_pending() -> None:
    assert _pending_charge().status == ChargeStatus.PENDING


def test_pending_transitions_to_succeeded() -> None:
    charge = transition_charge(_pending_charge(), ChargeStatus.SUCCEEDED)

    assert charge.status == ChargeStatus.SUCCEEDED


def test_pending_transitions_to_failed() -> None:
    charge = transition_charge(_pending_charge(), ChargeStatus.FAILED)

    assert charge.status == ChargeStatus.FAILED


def test_transition_returns_new_charge_without_mutating_original() -> None:
    original = _pending_charge()

    transition_charge(original, ChargeStatus.SUCCEEDED)

    assert original.status == ChargeStatus.PENDING


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (ChargeStatus.SUCCEEDED, ChargeStatus.FAILED),
        (ChargeStatus.SUCCEEDED, ChargeStatus.PENDING),
        (ChargeStatus.FAILED, ChargeStatus.SUCCEEDED),
        (ChargeStatus.FAILED, ChargeStatus.PENDING),
        (ChargeStatus.PENDING, ChargeStatus.PENDING),
    ],
)
def test_illegal_transition_raises(from_status: ChargeStatus, to_status: ChargeStatus) -> None:
    charge = _pending_charge().model_copy(update={"status": from_status})

    with pytest.raises(IllegalChargeTransitionError):
        transition_charge(charge, to_status)


def test_charge_rejects_period_end_before_start() -> None:
    with pytest.raises(ValueError, match="period_end"):
        Charge(
            id=1,
            subscription_id=1,
            amount_cents=1999,
            idempotency_key="evt_1",
            period_start=PERIOD_END,
            period_end=PERIOD_START,
        )
