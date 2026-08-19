from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELED = "canceled"


class Subscription(BaseModel):
    """A customer on a plan, with a current period (see CONTEXT.md: Subscription).

    The current period bounds the window a charge is raised for; ADR-0002 keeps
    all amounts in integer cents.
    """

    id: int
    customer_id: int
    plan_id: int
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: datetime
    current_period_end: datetime

    @model_validator(mode="after")
    def _check_period(self) -> "Subscription":
        if self.current_period_end <= self.current_period_start:
            msg = "current_period_end must be after current_period_start"
            raise ValueError(msg)
        return self
