import pytest
from pydantic import ValidationError

from orbit.models.plan import Plan, PlanInterval


def test_plan_holds_amount_in_integer_cents() -> None:
    plan = Plan(id=1, name="Pro Monthly", amount_cents=1999, interval=PlanInterval.MONTHLY)

    assert plan.amount_cents == 1999
    assert isinstance(plan.amount_cents, int)
    assert plan.interval == PlanInterval.MONTHLY


def test_plan_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        Plan(id=1, name="Broken", amount_cents=-1, interval=PlanInterval.YEARLY)


def test_plan_rejects_invalid_interval() -> None:
    with pytest.raises(ValidationError):
        Plan(id=1, name="Broken", amount_cents=100, interval="weekly")
