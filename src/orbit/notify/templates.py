"""Email templates for customer-facing billing notifications.

Per ADR-0002, amounts are formatted for display here, at the presentation
edge, from the integer cent value — never stored or passed around as such.
"""

from typing import Protocol

from orbit.billing.charges import Charge
from orbit.models.gift_card import GiftCard


class Customer(Protocol):
    """The customer fields a notification template needs."""

    @property
    def name(self) -> str: ...


def payment_failed(customer: Customer, charge: Charge) -> tuple[str, str]:
    """Build the (subject, body) of a payment-failed notification."""
    subject = "Your payment could not be processed"
    body = (
        f"Hi {customer.name},\n\n"
        f"We were unable to process your payment of {_format_cents(charge.amount_cents)}. "
        "Please check your payment method and try again.\n\n"
        "Thanks,\nThe Orbit team"
    )
    return subject, body


def gift_card_purchased(customer: Customer, gift_card: GiftCard) -> tuple[str, str]:
    """Build the (subject, body) of a gift-card-purchase confirmation, containing the code."""
    subject = "Your Orbit gift card is ready"
    body = (
        f"Hi {customer.name},\n\n"
        f"Thanks for your purchase of a {_format_cents(gift_card.face_value_cents)} gift card. "
        "Here is the code:\n\n"
        f"  {gift_card.code}\n\n"
        "Share it with anyone — they can redeem it at checkout.\n\n"
        "Thanks,\nThe Orbit team"
    )
    return subject, body


def _format_cents(amount_cents: int) -> str:
    dollars, cents = divmod(amount_cents, 100)
    return f"${dollars}.{cents:02d}"
