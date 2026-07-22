"""Payment-provider webhook receiver: validation and settlement.

Per ADR-0004, this path validates and enqueues (here: verifies the signature
and writes/updates rows that represent intent). It never calls the payment
provider — that is the worker's job. `receive_webhook` is the last stage of
the webhook pipeline: by the time it returns, the charge it concerns has
either settled (succeeded/failed) or was already settled by a prior delivery.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime

import asyncpg
from pydantic import BaseModel, Field

from orbit.billing.charges import Charge, ChargeStatus, transition_charge
from orbit.billing.idempotency import NewChargeRequest, get_or_create_charge_for_event
from orbit.billing.metrics import record_charge_outcome

logger = logging.getLogger(__name__)

_EVENT_OUTCOMES: dict[str, ChargeStatus] = {
    "charge.succeeded": ChargeStatus.SUCCEEDED,
    "charge.failed": ChargeStatus.FAILED,
}


class InvalidWebhookSignatureError(Exception):
    """Raised when a webhook's signature does not match the shared secret."""


class ChargeNotFoundError(Exception):
    """Raised when a charge_id does not correspond to any charge."""

    def __init__(self, charge_id: int) -> None:
        super().__init__(f"charge {charge_id} not found")
        self.charge_id = charge_id


class WebhookEventData(BaseModel):
    """The charge fields carried by a `charge.succeeded` / `charge.failed` event."""

    subscription_id: int
    amount_cents: int = Field(ge=0)
    period_start: datetime
    period_end: datetime


class WebhookEvent(BaseModel):
    """An inbound webhook from the payment provider (see CONTEXT.md: Event).

    `id` identifies the event and is stable across redeliveries (ADR-0001).
    `delivery_id` identifies this specific delivery attempt and is unique
    per redelivery of the same event — it exists for tracing, never for
    idempotency decisions.
    """

    id: str
    delivery_id: str
    type: str
    data: WebhookEventData


@dataclass(frozen=True, slots=True)
class WebhookIds:
    """Best-effort event/delivery identifiers, extracted before signature verification.

    Used only for logging and dead-letter bookkeeping — never for
    authorization or idempotency decisions, since the payload has not been
    verified or schema-validated yet when these are extracted.
    """

    event_id: str
    delivery_id: str


def extract_webhook_ids(payload: bytes) -> WebhookIds:
    """Best-effort extraction of `id`/`delivery_id` from a raw webhook payload.

    Falls back to `"unknown"` for either field if the payload isn't parseable
    JSON or is missing the field, so a single malformed delivery never breaks
    logging or dead-lettering for the rest of the pipeline.
    """
    try:
        raw = json.loads(payload)
        return WebhookIds(
            event_id=str(raw.get("id", "unknown")),
            delivery_id=str(raw.get("delivery_id", "unknown")),
        )
    except (json.JSONDecodeError, AttributeError):
        return WebhookIds(event_id="unknown", delivery_id="unknown")


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

    updated = await _settle_charge(conn, charge, new_status)
    logger.info(
        "webhook %s (delivery %s): charge %d settled as %s",
        event.id,
        event.delivery_id,
        updated.id,
        updated.status.value,
    )
    return updated


async def _settle_charge(
    conn: asyncpg.Connection, charge: Charge, new_status: ChargeStatus
) -> Charge:
    """Transition `charge` to `new_status` and record the outcome, in one transaction."""
    updated = transition_charge(charge, new_status)
    async with conn.transaction():
        await conn.execute(
            "UPDATE charges SET status = $1, updated_at = now() WHERE id = $2",
            updated.status.value,
            updated.id,
        )
        await record_charge_outcome(conn, updated.status)
    return updated


def _charge_from_row(row: asyncpg.Record) -> Charge:
    return Charge(
        id=row["id"],
        subscription_id=row["subscription_id"],
        amount_cents=row["amount_cents"],
        status=ChargeStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        period_start=row["period_start"],
        period_end=row["period_end"],
    )


async def replay_charge(conn: asyncpg.Connection, charge_id: int) -> Charge:
    """Re-attempt settling a charge stuck in `pending`, e.g. after a worker crash mid-flight.

    Replays the webhook event that originally created the charge through the
    same settlement path `receive_webhook` uses, without needing the payment
    provider to redeliver anything — the event was already verified and its
    payload persisted in `processed_events` when the charge was created.
    Idempotent: a charge that has already settled (by this replay, or by a
    webhook delivery that arrived in the meantime) is returned unchanged.
    """
    row = await conn.fetchrow("SELECT * FROM charges WHERE id = $1", charge_id)
    if row is None:
        raise ChargeNotFoundError(charge_id)

    charge = _charge_from_row(row)
    if charge.status is not ChargeStatus.PENDING:
        return charge

    event_payload = await conn.fetchval(
        "SELECT payload FROM processed_events WHERE charge_id = $1", charge_id
    )
    event = WebhookEvent.model_validate_json(event_payload)
    new_status = _EVENT_OUTCOMES[event.type]

    updated = await _settle_charge(conn, charge, new_status)
    logger.info("charge %d: replayed, settled as %s", updated.id, updated.status.value)
    return updated
