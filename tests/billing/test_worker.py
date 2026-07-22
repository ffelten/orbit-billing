import hashlib
import hmac
import json
import logging
import random
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from orbit.billing.charges import ChargeStatus
from orbit.billing.webhooks import InvalidWebhookSignatureError
from orbit.billing.worker import (
    MAX_ATTEMPTS,
    RetriesExhaustedError,
    _backoff_seconds,
    process_webhook_with_retry,
)

SECRET = "whsec_test_secret"  # noqa: S105 -- test fixture, not a real credential
PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(days=30)


async def _seed_subscription(conn: asyncpg.Connection) -> int:
    customer_id = await conn.fetchval(
        "INSERT INTO customers (email) VALUES ($1) RETURNING id", "customer@example.com"
    )
    plan_id = await conn.fetchval(
        "INSERT INTO plans (name, amount_cents, interval) VALUES ($1, $2, $3) RETURNING id",
        "Pro Monthly",
        1999,
        "monthly",
    )
    return await conn.fetchval(
        """
        INSERT INTO subscriptions
            (customer_id, plan_id, status, current_period_start, current_period_end)
        VALUES ($1, $2, 'active', $3, $4)
        RETURNING id
        """,
        customer_id,
        plan_id,
        PERIOD_START,
        PERIOD_END,
    )


def _event_payload(
    event_id: str, event_type: str, subscription_id: int, delivery_id: str = "dlv_1"
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "delivery_id": delivery_id,
            "type": event_type,
            "data": {
                "subscription_id": subscription_id,
                "amount_cents": 1999,
                "period_start": PERIOD_START.isoformat(),
                "period_end": PERIOD_END.isoformat(),
            },
        }
    ).encode()


def _sign(payload: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class _FakeClock:
    """Records sleep durations instead of actually waiting."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class _FlakyConnection:
    """Wraps a real connection, failing the first N calls to `execute`."""

    def __init__(self, conn: asyncpg.Connection, failures: int, error: Exception) -> None:
        self._conn = conn
        self._failures = failures
        self._error = error
        self.calls = 0

    async def execute(self, *args: object, **kwargs: object) -> str:
        self.calls += 1
        if self.calls <= self._failures:
            raise self._error
        return await self._conn.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


async def test_succeeds_on_first_attempt_without_sleeping(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    clock = _FakeClock()

    charge = await process_webhook_with_retry(
        db_conn, payload=payload, signature=_sign(payload), secret=SECRET, sleep=clock.sleep
    )

    assert charge is not None
    assert charge.status == ChargeStatus.SUCCEEDED
    assert clock.slept == []


async def test_retries_transient_failure_then_succeeds(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    flaky = _FlakyConnection(
        db_conn, failures=2, error=asyncpg.ConnectionDoesNotExistError("connection lost")
    )
    clock = _FakeClock()

    charge = await process_webhook_with_retry(
        flaky, payload=payload, signature=_sign(payload), secret=SECRET, sleep=clock.sleep
    )

    assert charge is not None
    assert charge.status == ChargeStatus.SUCCEEDED
    # 2 failing attempts each consume 1 execute() before their transaction rolls back;
    # the successful attempt consumes 3 (create charge, transition it, record the
    # outcome counter).
    assert flaky.calls == 5
    assert len(clock.slept) == 2


async def test_gives_up_after_max_attempts(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    flaky = _FlakyConnection(
        db_conn,
        failures=MAX_ATTEMPTS,
        error=asyncpg.ConnectionDoesNotExistError("connection lost"),
    )
    clock = _FakeClock()

    with pytest.raises(RetriesExhaustedError):
        await process_webhook_with_retry(
            flaky, payload=payload, signature=_sign(payload), secret=SECRET, sleep=clock.sleep
        )

    # MAX_ATTEMPTS failing execute() calls, plus one more that succeeds:
    # the dead-letter row recording the exhausted delivery.
    assert flaky.calls == MAX_ATTEMPTS + 1
    assert len(clock.slept) == MAX_ATTEMPTS - 1

    dead_letters = await db_conn.fetch("SELECT * FROM webhook_dead_letters")
    assert len(dead_letters) == 1
    assert dead_letters[0]["provider_event_id"] == "evt_1"
    assert dead_letters[0]["delivery_id"] == "dlv_1"
    assert dead_letters[0]["attempts"] == MAX_ATTEMPTS


async def test_permanent_error_is_not_retried(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    clock = _FakeClock()

    with pytest.raises(InvalidWebhookSignatureError):
        await process_webhook_with_retry(
            db_conn,
            payload=payload,
            signature="forged-signature",
            secret=SECRET,
            sleep=clock.sleep,
        )

    assert clock.slept == []
    charge_count = await db_conn.fetchval("SELECT count(*) FROM charges")
    assert charge_count == 0


async def test_logs_each_attempt(
    db_conn: asyncpg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    flaky = _FlakyConnection(
        db_conn, failures=1, error=asyncpg.ConnectionDoesNotExistError("connection lost")
    )
    clock = _FakeClock()

    with caplog.at_level(logging.INFO, logger="orbit.billing.worker"):
        await process_webhook_with_retry(
            flaky, payload=payload, signature=_sign(payload), secret=SECRET, sleep=clock.sleep
        )

    messages = [record.message for record in caplog.records]
    assert any("attempt 1/5 failed" in message for message in messages)
    assert any("attempt 2/5 succeeded" in message for message in messages)


def test_backoff_grows_exponentially() -> None:
    rng = random.Random(0)  # noqa: S311 -- deterministic seed for a jitter test, not crypto
    ceilings = [0.5 * (2**exponent) for exponent in range(MAX_ATTEMPTS)]

    for attempt, ceiling in enumerate(ceilings, start=1):
        delay = _backoff_seconds(attempt, rng)
        assert 0 <= delay <= ceiling


def test_backoff_is_jittered_not_fixed() -> None:
    rng = random.Random(0)  # noqa: S311 -- deterministic seed for a jitter test, not crypto
    delays = {_backoff_seconds(3, rng) for _ in range(20)}

    assert len(delays) > 1
