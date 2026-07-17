"""Webhook processing worker: retries transient failures with backoff (ADR-0003).

Per ADR-0004, the worker is the only thing that talks to the payment
provider and owns retry/backoff behavior; `receive_webhook` itself makes no
outbound calls and only writes rows representing intent. What this module
adds is resilience against transient failures in that write path (DB blips,
connection timeouts) — not a payment provider integration.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable

import asyncpg

from orbit.billing.charges import Charge
from orbit.billing.webhooks import receive_webhook

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_BASE_DELAY_SECONDS = 0.5

# Errors that indicate a transient DB/network problem, worth retrying.
# Everything else (bad signature, malformed payload, illegal transition) is
# permanent — retrying it would just fail the same way every time.
_RETRYABLE_ERRORS = (asyncpg.PostgresConnectionError, TimeoutError, OSError)


class RetriesExhaustedError(Exception):
    """Raised when a webhook still fails after MAX_ATTEMPTS attempts."""


def _backoff_seconds(attempt: int, rng: random.Random) -> float:
    """Full-jitter exponential backoff for the given (1-indexed) attempt.

    Jitter (a random delay between 0 and the exponential ceiling, rather
    than the ceiling itself) is what keeps a batch of events that failed
    together from retrying together and hammering a provider that just
    recovered.
    """
    ceiling = _BASE_DELAY_SECONDS * (2 ** (attempt - 1))
    return rng.uniform(0, ceiling)


def _event_id(payload: bytes) -> str:
    try:
        return str(json.loads(payload).get("id", "unknown"))
    except (json.JSONDecodeError, AttributeError):
        return "unknown"


async def process_webhook_with_retry(  # noqa: PLR0913 -- mirrors receive_webhook's params,
    # plus sleep/rng hooks that let tests replace real waiting/randomness
    conn: asyncpg.Connection,
    *,
    payload: bytes,
    signature: str,
    secret: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> Charge | None:
    """Process one webhook delivery, retrying transient failures (ADR-0003).

    Retries at most MAX_ATTEMPTS times with jittered exponential backoff.
    Signature and validation errors are not retried since they are permanent
    and would fail identically on every attempt. Raises `RetriesExhaustedError`
    if every attempt fails, surfacing the event as failed for manual
    investigation.
    """
    rng = rng if rng is not None else random.Random()  # noqa: S311 -- jitter timing, not crypto
    event_id = _event_id(payload)
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            charge = await receive_webhook(
                conn, payload=payload, signature=signature, secret=secret
            )
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "webhook %s: attempt %d/%d failed: %s", event_id, attempt, MAX_ATTEMPTS, exc
            )
            if attempt < MAX_ATTEMPTS:
                await sleep(_backoff_seconds(attempt, rng))
            continue
        else:
            logger.info("webhook %s: attempt %d/%d succeeded", event_id, attempt, MAX_ATTEMPTS)
            return charge

    logger.error("webhook %s: giving up after %d attempts", event_id, MAX_ATTEMPTS)
    msg = f"webhook {event_id} still failing after {MAX_ATTEMPTS} attempts"
    raise RetriesExhaustedError(msg) from last_error
