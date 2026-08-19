"""HTTP routes. Per ADR-0004, handlers validate and enqueue only."""

import logging
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from orbit.billing import dead_letter, metrics
from orbit.billing.gift_cards import CustomerNotFoundError, issue_gift_cards_bulk
from orbit.billing.subscriptions import (
    PlanNotFoundError,
    SubscriptionNotFoundError,
    change_subscription_plan,
)
from orbit.billing.webhooks import InvalidWebhookSignatureError, extract_webhook_ids
from orbit.billing.worker import RetriesExhaustedError, process_webhook_with_retry
from orbit.db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()

_SIGNATURE_HEADER = "X-Provider-Signature"
_ADMIN_SCOPES_HEADER = "X-Admin-Scopes"


def require_admin_scope(scope: str) -> Callable[[Request], None]:
    """Build a dependency that 403s unless `scope` was granted to the caller.

    Scope grants are resolved upstream (API gateway or auth middleware) and
    passed through as a comma-separated `X-Admin-Scopes` header; this
    dependency only checks that the required scope is present, it does not
    authenticate the caller.
    """

    def _require_admin_scope(request: Request) -> None:
        granted = {
            s.strip() for s in request.headers.get(_ADMIN_SCOPES_HEADER, "").split(",") if s.strip()
        }
        if scope not in granted:
            raise HTTPException(status_code=403, detail=f"missing required scope: {scope}")

    return _require_admin_scope


@router.post("/webhooks/provider", status_code=202)
async def receive_provider_webhook(
    request: Request,
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> dict[str, bool]:
    """Accept a payment-provider webhook delivery.

    Verifies the signature, then validates and enqueues per ADR-0004 — this
    handler makes no outbound calls to the payment provider. This is the
    receipt stage of the webhook pipeline; see `process_webhook_with_retry`
    for retry/backoff and `orbit.billing.webhooks.receive_webhook` for
    validation and settlement.
    """
    signature = request.headers.get(_SIGNATURE_HEADER)
    if signature is None:
        raise HTTPException(status_code=400, detail=f"missing {_SIGNATURE_HEADER} header")

    secret = os.environ["PROVIDER_WEBHOOK_SECRET"]
    payload = await request.body()
    ids = extract_webhook_ids(payload)
    logger.info("webhook %s (delivery %s): received", ids.event_id, ids.delivery_id)

    try:
        await process_webhook_with_retry(conn, payload=payload, signature=signature, secret=secret)
    except InvalidWebhookSignatureError as exc:
        logger.warning("webhook %s (delivery %s): invalid signature", ids.event_id, ids.delivery_id)
        raise HTTPException(status_code=400, detail="invalid signature") from exc
    except ValidationError as exc:
        logger.warning("webhook %s (delivery %s): malformed payload", ids.event_id, ids.delivery_id)
        raise HTTPException(status_code=400, detail="malformed webhook payload") from exc
    except RetriesExhaustedError as exc:
        raise HTTPException(status_code=502, detail="webhook processing failed") from exc

    return {"received": True}


class DeadLetterEntry(BaseModel):
    id: int
    provider_event_id: str
    delivery_id: str
    payload: dict[str, object]
    error_message: str
    attempts: int
    failed_at: datetime


@router.get("/webhooks/dead-letter")
async def list_webhook_dead_letters(
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> list[DeadLetterEntry]:
    """List webhook deliveries that exhausted all retry attempts, most recent first.

    Lets support see what got dropped without digging through logs.
    """
    entries = await dead_letter.list_dead_letters(conn)
    return [
        DeadLetterEntry(
            id=entry.id,
            provider_event_id=entry.provider_event_id,
            delivery_id=entry.delivery_id,
            payload=entry.payload,
            error_message=entry.error_message,
            attempts=entry.attempts,
            failed_at=entry.failed_at,
        )
        for entry in entries
    ]


class ChargeOutcomeCounts(BaseModel):
    day: date
    succeeded: int
    failed: int


@router.get("/metrics/charges")
async def get_charge_metrics(
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> list[ChargeOutcomeCounts]:
    """Charge outcome counts by day (succeeded vs failed), most recent day first."""
    daily_counts = await metrics.list_charge_outcomes_by_day(conn)
    return [
        ChargeOutcomeCounts(day=d.day, succeeded=d.succeeded, failed=d.failed) for d in daily_counts
    ]


class ChangePlanRequest(BaseModel):
    plan_id: int


class ChangePlanResponse(BaseModel):
    subscription_id: int
    previous_plan_id: int
    new_plan_id: int
    prorated_amount_cents: int


@router.post("/subscriptions/{subscription_id}/plan")
async def change_subscription_plan_route(
    subscription_id: int,
    body: ChangePlanRequest,
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> ChangePlanResponse:
    """Change a subscription's plan, returning the prorated amount owed or credited.

    `prorated_amount_cents` follows the sign convention of
    `prorated_amount_cents()` in `orbit.billing.proration`: positive means
    the customer owes the difference, negative means they're credited.
    """
    try:
        result = await change_subscription_plan(
            conn,
            subscription_id=subscription_id,
            new_plan_id=body.plan_id,
            changed_at=datetime.now(UTC),
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subscription not found") from exc
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=400, detail="plan not found") from exc

    return ChangePlanResponse(
        subscription_id=result.subscription_id,
        previous_plan_id=result.previous_plan_id,
        new_plan_id=result.new_plan_id,
        prorated_amount_cents=result.prorated_amount_cents,
    )


class BulkIssueGiftCardsRequest(BaseModel):
    customer_id: int
    count: int = Field(gt=0, le=1000)
    face_value_cents: int = Field(gt=0)


class IssuedGiftCard(BaseModel):
    id: int
    code: str
    face_value_cents: int
    expires_at: datetime


class BulkIssueGiftCardsResponse(BaseModel):
    gift_cards: list[IssuedGiftCard]


@router.post(
    "/admin/gift-cards/bulk",
    status_code=201,
    dependencies=[Depends(require_admin_scope("admin:gift-cards"))],
)
async def bulk_issue_gift_cards_route(
    body: BulkIssueGiftCardsRequest,
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> BulkIssueGiftCardsResponse:
    """Issue `count` gift cards of `face_value_cents`, all owned by `customer_id`.

    For corporate clients buying gift cards in bulk to hand out themselves
    (see docs/prd/gift-cards.md). Requires the `admin:gift-cards` scope.
    """
    try:
        gift_cards = await issue_gift_cards_bulk(
            conn,
            customer_id=body.customer_id,
            count=body.count,
            face_value_cents=body.face_value_cents,
            funded_at=datetime.now(UTC),
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail="customer not found") from exc

    return BulkIssueGiftCardsResponse(
        gift_cards=[
            IssuedGiftCard(
                id=gc.id,
                code=gc.code,
                face_value_cents=gc.face_value_cents,
                expires_at=gc.expires_at,
            )
            for gc in gift_cards
        ]
    )
