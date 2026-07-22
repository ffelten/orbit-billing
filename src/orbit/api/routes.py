"""HTTP routes. Per ADR-0004, handlers validate and enqueue only."""

import os
from datetime import UTC, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from orbit.billing.subscriptions import (
    PlanNotFoundError,
    SubscriptionNotFoundError,
    change_subscription_plan,
)
from orbit.billing.summary import CustomerNotFoundError, get_billing_summary
from orbit.billing.webhooks import InvalidWebhookSignatureError
from orbit.billing.worker import RetriesExhaustedError, process_webhook_with_retry
from orbit.db import get_connection

router = APIRouter()

_SIGNATURE_HEADER = "X-Provider-Signature"


@router.post("/webhooks/provider", status_code=202)
async def receive_provider_webhook(
    request: Request,
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> dict[str, bool]:
    """Accept a payment-provider webhook delivery.

    Verifies the signature, then validates and enqueues per ADR-0004 — this
    handler makes no outbound calls to the payment provider.
    """
    signature = request.headers.get(_SIGNATURE_HEADER)
    if signature is None:
        raise HTTPException(status_code=400, detail=f"missing {_SIGNATURE_HEADER} header")

    secret = os.environ["PROVIDER_WEBHOOK_SECRET"]
    payload = await request.body()

    try:
        await process_webhook_with_retry(conn, payload=payload, signature=signature, secret=secret)
    except InvalidWebhookSignatureError as exc:
        raise HTTPException(status_code=400, detail="invalid signature") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="malformed webhook payload") from exc
    except RetriesExhaustedError as exc:
        raise HTTPException(status_code=502, detail="webhook processing failed") from exc

    return {"received": True}


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


class ActiveSubscriptionResponse(BaseModel):
    plan_name: str
    amount_cents: int
    interval: str


class ChargeSummaryResponse(BaseModel):
    id: int
    amount_cents: int
    status: str
    created_at: datetime


class BillingSummaryResponse(BaseModel):
    customer_id: int
    active_subscription: ActiveSubscriptionResponse | None
    recent_charges: list[ChargeSummaryResponse]
    total_charged_cents: int


@router.get("/customers/{customer_id}/billing-summary")
async def get_customer_billing_summary_route(
    customer_id: int,
    conn: Annotated[asyncpg.Connection, Depends(get_connection)],
) -> BillingSummaryResponse:
    """Return a customer's active subscription, most recent charges, and total amount charged."""
    try:
        summary = await get_billing_summary(conn, customer_id=customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail="customer not found") from exc

    active_subscription = (
        ActiveSubscriptionResponse(
            plan_name=summary.active_subscription.plan_name,
            amount_cents=summary.active_subscription.amount_cents,
            interval=summary.active_subscription.interval,
        )
        if summary.active_subscription is not None
        else None
    )

    return BillingSummaryResponse(
        customer_id=summary.customer_id,
        active_subscription=active_subscription,
        recent_charges=[
            ChargeSummaryResponse(
                id=charge.id,
                amount_cents=charge.amount_cents,
                status=charge.status,
                created_at=charge.created_at,
            )
            for charge in summary.recent_charges
        ],
        total_charged_cents=summary.total_charged_cents,
    )
