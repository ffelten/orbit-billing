"""Payment-provider webhook receiver.

Per ADR-0004, this path validates and enqueues (here: verifies the signature
and writes/updates rows that represent intent). It never calls the payment
provider — that is the worker's job.
"""

import hashlib
import hmac
import json
from datetime import datetime

import asyncpg
from pydantic import BaseModel, Field

from orbit.billing.charges import Charge, ChargeStatus, transition_charge
from orbit.billing.idempotency import NewChargeRequest, get_or_create_charge_for_event

_EVENT_OUTCOMES: dict[str, ChargeStatus] = {
    "charge.succeeded": ChargeStatus.SUCCEEDED,
    "charge.failed": ChargeStatus.FAILED,
}


class InvalidWebhookSignatureError(Exception):
    """Raised when a webhook's signature does not match the shared secret."""


class WebhookEventData(BaseModel):
    """The charge fields carried by a `charge.succeeded` / `charge.failed` event."""

    subscription_id: int
    amount_cents: int = Field(ge=0)
    period_start: datetime
    period_end: datetime


class WebhookEvent(BaseModel):
    """An inbound webhook from the payment provider (see CONTEXT.md: Event)."""

    id: str
    type: str
    data: WebhookEventData


def verify_signature(payload: bytes, signature: str, secret: str) -> None:
    """Verify `payload` was signed with `secret`, raising if it was not.

    Uses a constant-time comparison so verification failures don't leak
    timing information about the expected signature.
    """
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidWebhookSignatureError


async def receive_webhook(
    conn: asyncpg.Connection,
    *,
    payload: bytes,
    signature: str,
    secret: str,
) -> Charge | None:
    """Verify and process one payment-provider webhook delivery.

    Unknown event types are acknowledged and ignored. For
    `charge.succeeded` / `charge.failed`, the associated charge is created
    (if this is the first delivery for the event) and moved through the
    state machine (ADR charge state machine). A redelivery of an
    already-processed event returns the existing charge unchanged rather
    than transitioning or duplicating it (ADR-0001).
    """
    verify_signature(payload, signature, secret)
    event = WebhookEvent.model_validate_json(payload)

    new_status = _EVENT_OUTCOMES.get(event.type)
    if new_status is None:
        return None

    request = NewChargeRequest(
        subscription_id=event.data.subscription_id,
        amount_cents=event.data.amount_cents,
        period_start=event.data.period_start,
        period_end=event.data.period_end,
    )
    charge = await get_or_create_charge_for_event(conn, event.id, json.loads(payload), request)

    if charge.status is not ChargeStatus.PENDING:
        return charge

    updated = transition_charge(charge, new_status)
    await conn.execute(
        "UPDATE charges SET status = $1, updated_at = now() WHERE id = $2",
        updated.status.value,
        updated.id,
    )
    return updated
