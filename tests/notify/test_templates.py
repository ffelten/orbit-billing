from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from orbit.billing.charges import Charge
from orbit.notify.templates import payment_failed

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


@dataclass(frozen=True, slots=True)
class _Customer:
    name: str


def _charge(amount_cents: int) -> Charge:
    return Charge(
        id=1,
        subscription_id=1,
        amount_cents=amount_cents,
        idempotency_key="evt_1",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )


def test_payment_failed_returns_a_subject() -> None:
    subject, _ = payment_failed(_Customer(name="Ada Lovelace"), _charge(1999))

    assert subject


def test_payment_failed_renders_customer_name() -> None:
    _, body = payment_failed(_Customer(name="Ada Lovelace"), _charge(1999))

    assert "Ada Lovelace" in body


def test_payment_failed_renders_amount_as_formatted_currency() -> None:
    _, body = payment_failed(_Customer(name="Ada Lovelace"), _charge(1999))

    assert "$19.99" in body


def test_payment_failed_formats_whole_dollar_amount() -> None:
    _, body = payment_failed(_Customer(name="Ada Lovelace"), _charge(500))

    assert "$5.00" in body


def test_payment_failed_formats_sub_dollar_amount() -> None:
    _, body = payment_failed(_Customer(name="Ada Lovelace"), _charge(9))

    assert "$0.09" in body
