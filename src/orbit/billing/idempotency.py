"""Idempotent charge creation from payment-provider webhook events (ADR-0001)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from orbit.billing.charges import Charge, ChargeStatus


def derive_idempotency_key(provider_event_id: str) -> str:
    """Derive a charge's idempotency key from a payment provider event ID.

    Per ADR-0001, this is a pure, deterministic function of the event ID
    alone — never a timestamp, request ID, or anything else that changes
    between redeliveries of the same event.
    """
    if not provider_event_id:
        msg = "provider_event_id must not be empty"
        raise ValueError(msg)
    return provider_event_id


@dataclass(frozen=True, slots=True)
class NewChargeRequest:
    """The charge to create if this event has not been processed before."""

    subscription_id: int
    amount_cents: int
    period_start: datetime
    period_end: datetime


async def get_or_create_charge_for_event(
    conn: asyncpg.Connection,
    provider_event_id: str,
    payload: Mapping[str, object],
    request: NewChargeRequest,
) -> Charge:
    """Process a webhook event exactly once, returning its charge.

    If `provider_event_id` has not been seen before, records it and creates
    a new pending charge. If it has (a redelivery), returns the charge from
    the original processing — no new charge is created.

    The guarantee is enforced by the unique constraint on
    `processed_events.provider_event_id`: concurrent redeliveries serialize
    on that constraint at the database level, not only in this code.
    """
    idempotency_key = derive_idempotency_key(provider_event_id)

    async with conn.transaction():
        inserted_event = await conn.fetchrow(
            """
            INSERT INTO processed_events (provider_event_id, payload)
            VALUES ($1, $2)
            ON CONFLICT (provider_event_id) DO NOTHING
            RETURNING id
            """,
            provider_event_id,
            json.dumps(payload),
        )

        if inserted_event is None:
            return await _load_charge_for_event(conn, provider_event_id)

        charge_row = await conn.fetchrow(
            """
            INSERT INTO charges (
                subscription_id, amount_cents, idempotency_key, period_start, period_end
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            request.subscription_id,
            request.amount_cents,
            idempotency_key,
            request.period_start,
            request.period_end,
        )

        await conn.execute(
            "UPDATE processed_events SET charge_id = $1 WHERE provider_event_id = $2",
            charge_row["id"],
            provider_event_id,
        )

    return _charge_from_row(charge_row)


async def _load_charge_for_event(conn: asyncpg.Connection, provider_event_id: str) -> Charge:
    row = await conn.fetchrow(
        """
        SELECT c.*
        FROM charges c
        JOIN processed_events pe ON pe.charge_id = c.id
        WHERE pe.provider_event_id = $1
        """,
        provider_event_id,
    )
    if row is None:
        msg = f"event {provider_event_id!r} was processed but has no charge yet"
        raise LookupError(msg)
    return _charge_from_row(row)


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
