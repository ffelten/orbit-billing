from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ChargeStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[ChargeStatus, frozenset[ChargeStatus]] = {
    ChargeStatus.PENDING: frozenset({ChargeStatus.SUCCEEDED, ChargeStatus.FAILED}),
    ChargeStatus.SUCCEEDED: frozenset(),
    ChargeStatus.FAILED: frozenset(),
}


class IllegalChargeTransitionError(Exception):
    """Raised when a charge transition is not allowed by the state machine."""

    def __init__(self, from_status: ChargeStatus, to_status: ChargeStatus) -> None:
        super().__init__(f"cannot transition charge from {from_status!r} to {to_status!r}")
        self.from_status = from_status
        self.to_status = to_status


class Charge(BaseModel):
    """One unit of money owed for one subscription period.

    States: pending -> succeeded | failed. A charge is created once per
    period and is never duplicated by retries (ADR-0001).
    """

    id: int
    subscription_id: int
    amount_cents: int = Field(ge=0)
    status: ChargeStatus = ChargeStatus.PENDING
    idempotency_key: str
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def _check_period(self) -> "Charge":
        if self.period_end <= self.period_start:
            msg = "period_end must be after period_start"
            raise ValueError(msg)
        return self


def transition_charge(charge: Charge, new_status: ChargeStatus) -> Charge:
    """Move `charge` to `new_status`, enforcing the pending -> succeeded|failed state machine."""
    if new_status not in _ALLOWED_TRANSITIONS[charge.status]:
        raise IllegalChargeTransitionError(charge.status, new_status)
    return charge.model_copy(update={"status": new_status})
