from enum import StrEnum

from pydantic import BaseModel, Field


class PlanInterval(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class Plan(BaseModel):
    """A named price point.

    Amounts are integer cents per ADR-0002; floats never touch money.
    """

    id: int
    name: str
    amount_cents: int = Field(ge=0)
    interval: PlanInterval
