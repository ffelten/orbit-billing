from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class GiftCard(BaseModel):
    """A prepaid balance, identified by a code, redeemable at checkout (see CONTEXT.md).

    Amounts are integer cents per ADR-0002. Gift cards never expire.
    """

    id: int
    code: str
    purchaser_customer_id: int
    initial_amount_cents: int = Field(ge=0)
    balance_cents: int = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def _check_balance(self) -> "GiftCard":
        if self.balance_cents > self.initial_amount_cents:
            msg = "balance_cents must not exceed initial_amount_cents"
            raise ValueError(msg)
        return self
