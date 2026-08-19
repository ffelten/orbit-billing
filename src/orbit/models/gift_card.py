from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class GiftCard(BaseModel):
    """A stored-value code a customer buys and someone else redeems.

    Amounts are integer cents per ADR-0002; floats never touch money.
    Balances expire twelve months after funding per ADR-0005.
    """

    id: int
    customer_id: int
    code: str
    amount_cents: int = Field(gt=0)
    balance_cents: int = Field(ge=0)
    funded_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _check_balance(self) -> "GiftCard":
        if self.balance_cents > self.amount_cents:
            msg = "balance_cents must not exceed amount_cents"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_expiry(self) -> "GiftCard":
        if self.expires_at <= self.funded_at:
            msg = "expires_at must be after funded_at"
            raise ValueError(msg)
        return self
