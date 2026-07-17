"""HTTP routes. Per ADR-0004, handlers validate and enqueue only."""

import os
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from orbit.billing.webhooks import InvalidWebhookSignatureError, receive_webhook
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
        await receive_webhook(conn, payload=payload, signature=signature, secret=secret)
    except InvalidWebhookSignatureError as exc:
        raise HTTPException(status_code=400, detail="invalid signature") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="malformed webhook payload") from exc

    return {"received": True}
