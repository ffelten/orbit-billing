from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from orbit.models.subscription import Subscription, SubscriptionStatus

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


def test_subscription_defaults_to_active() -> None:
    subscription = Subscription(
        id=1,
        customer_id=1,
        plan_id=1,
        current_period_start=PERIOD_START,
        current_period_end=PERIOD_END,
    )

    assert subscription.status == SubscriptionStatus.ACTIVE


def test_subscription_rejects_period_end_before_start() -> None:
    with pytest.raises(ValueError, match="current_period_end"):
        Subscription(
            id=1,
            customer_id=1,
            plan_id=1,
            current_period_start=PERIOD_END,
            current_period_end=PERIOD_START,
        )


def test_subscription_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        Subscription(
            id=1,
            customer_id=1,
            plan_id=1,
            status="trial",
            current_period_start=PERIOD_START,
            current_period_end=PERIOD_END,
        )
