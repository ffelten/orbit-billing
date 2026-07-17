"""Dead-letter storage for webhook events that exhaust all retry attempts (ADR-0003).

This is the terminal sink `process_webhook_with_retry` writes to instead of
letting a permanently-failing delivery vanish after its last log line — see
`orbit.billing.worker.process_webhook_with_retry`.
"""

import json
from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """One webhook delivery that failed on every retry attempt."""

    id: int
    provider_event_id: str
    delivery_id: str
    payload: dict[str, object]
    error_message: str
    attempts: int
    failed_at: datetime


async def record_dead_letter(  # noqa: PLR0913 -- one field per dead-letter column
    conn: asyncpg.Connection,
    *,
    provider_event_id: str,
    delivery_id: str,
    payload: bytes,
    error_message: str,
    attempts: int,
) -> None:
    """Persist a webhook delivery that exhausted all retry attempts.

    `payload` is the raw request body; by the time retries are exhausted it
    has already round-tripped through `WebhookEvent.model_validate_json` at
    least once (only transient DB/network errors are retried — see
    `orbit.billing.worker._RETRYABLE_ERRORS`), so it is expected to be valid
    JSON. It is decoded defensively anyway since this is a last-resort sink
    that must not itself raise and mask the real failure.
    """
    try:
        payload_json = json.loads(payload)
    except json.JSONDecodeError:
        payload_json = {"raw": payload.decode(errors="replace")}

    await conn.execute(
        """
        INSERT INTO webhook_dead_letters
            (provider_event_id, delivery_id, payload, error_message, attempts)
        VALUES ($1, $2, $3, $4, $5)
        """,
        provider_event_id,
        delivery_id,
        json.dumps(payload_json),
        error_message,
        attempts,
    )


async def list_dead_letters(conn: asyncpg.Connection) -> list[DeadLetter]:
    """List dead-lettered webhook deliveries, most recently failed first."""
    rows = await conn.fetch(
        """
        SELECT id, provider_event_id, delivery_id, payload, error_message, attempts, failed_at
        FROM webhook_dead_letters
        ORDER BY failed_at DESC
        """
    )
    return [
        DeadLetter(
            id=row["id"],
            provider_event_id=row["provider_event_id"],
            delivery_id=row["delivery_id"],
            payload=json.loads(row["payload"]),
            error_message=row["error_message"],
            attempts=row["attempts"],
            failed_at=row["failed_at"],
        )
        for row in rows
    ]
