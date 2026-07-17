import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from pydantic import ValidationError

from orbit.billing.charges import ChargeStatus, IllegalChargeTransitionError
from orbit.billing.webhooks import (
    InvalidWebhookSignatureError,
    WebhookEvent,
    extract_webhook_ids,
    receive_webhook,
    verify_signature,
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


def test_verify_signature_accepts_matching_signature() -> None:
    payload = b'{"id": "evt_1"}'
    verify_signature(payload, _sign(payload), SECRET)


def test_verify_signature_rejects_wrong_signature() -> None:
    payload = b'{"id": "evt_1"}'
    with pytest.raises(InvalidWebhookSignatureError):
        verify_signature(payload, "not-the-right-signature", SECRET)


async def test_bad_signature_is_rejected(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)

    with pytest.raises(InvalidWebhookSignatureError):
        await receive_webhook(db_conn, payload=payload, signature="forged-signature", secret=SECRET)

    charge_count = await db_conn.fetchval("SELECT count(*) FROM charges")
    assert charge_count == 0


async def test_charge_succeeded_moves_charge_to_succeeded(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)

    charge = await receive_webhook(
        db_conn, payload=payload, signature=_sign(payload), secret=SECRET
    )

    assert charge is not None
    assert charge.status == ChargeStatus.SUCCEEDED
    stored_status = await db_conn.fetchval("SELECT status FROM charges WHERE id = $1", charge.id)
    assert stored_status == "succeeded"


async def test_charge_failed_moves_charge_to_failed(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.failed", subscription_id)

    charge = await receive_webhook(
        db_conn, payload=payload, signature=_sign(payload), secret=SECRET
    )

    assert charge is not None
    assert charge.status == ChargeStatus.FAILED
    stored_status = await db_conn.fetchval("SELECT status FROM charges WHERE id = $1", charge.id)
    assert stored_status == "failed"


async def test_redelivered_event_is_a_no_op(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    signature = _sign(payload)

    first = await receive_webhook(db_conn, payload=payload, signature=signature, secret=SECRET)
    second = await receive_webhook(db_conn, payload=payload, signature=signature, secret=SECRET)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert second.status == ChargeStatus.SUCCEEDED
    charge_count = await db_conn.fetchval("SELECT count(*) FROM charges")
    assert charge_count == 1


async def test_redelivered_event_does_not_attempt_illegal_transition(
    db_conn: asyncpg.Connection,
) -> None:
    subscription_id = await _seed_subscription(db_conn)
    succeeded_payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    failed_payload = _event_payload("evt_1", "charge.failed", subscription_id)

    await receive_webhook(
        db_conn, payload=succeeded_payload, signature=_sign(succeeded_payload), secret=SECRET
    )

    try:
        result = await receive_webhook(
            db_conn, payload=failed_payload, signature=_sign(failed_payload), secret=SECRET
        )
    except IllegalChargeTransitionError:
        pytest.fail("redelivery of an already-processed event must be a no-op, not a transition")

    assert result is not None
    assert result.status == ChargeStatus.SUCCEEDED


async def test_unknown_event_type_is_ignored(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.refunded", subscription_id)

    result = await receive_webhook(
        db_conn, payload=payload, signature=_sign(payload), secret=SECRET
    )

    assert result is None
    charge_count = await db_conn.fetchval("SELECT count(*) FROM charges")
    assert charge_count == 0


async def test_settling_a_charge_increments_the_daily_outcome_counter(
    db_conn: asyncpg.Connection,
) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)

    await receive_webhook(db_conn, payload=payload, signature=_sign(payload), secret=SECRET)

    count = await db_conn.fetchval(
        "SELECT count FROM charge_outcome_counts WHERE day = current_date AND status = 'succeeded'"
    )
    assert count == 1


async def test_redelivery_does_not_double_count_the_outcome(db_conn: asyncpg.Connection) -> None:
    subscription_id = await _seed_subscription(db_conn)
    payload = _event_payload("evt_1", "charge.succeeded", subscription_id)
    signature = _sign(payload)

    await receive_webhook(db_conn, payload=payload, signature=signature, secret=SECRET)
    await receive_webhook(db_conn, payload=payload, signature=signature, secret=SECRET)

    count = await db_conn.fetchval(
        "SELECT count FROM charge_outcome_counts WHERE day = current_date AND status = 'succeeded'"
    )
    assert count == 1


def test_webhook_event_requires_delivery_id() -> None:
    payload = json.dumps(
        {
            "id": "evt_1",
            "type": "charge.succeeded",
            "data": {
                "subscription_id": 1,
                "amount_cents": 1999,
                "period_start": PERIOD_START.isoformat(),
                "period_end": PERIOD_END.isoformat(),
            },
        }
    ).encode()

    with pytest.raises(ValidationError):
        WebhookEvent.model_validate_json(payload)


def test_extract_webhook_ids_reads_id_and_delivery_id() -> None:
    payload = _event_payload("evt_1", "charge.succeeded", 1, delivery_id="dlv_42")

    ids = extract_webhook_ids(payload)

    assert ids.event_id == "evt_1"
    assert ids.delivery_id == "dlv_42"


def test_extract_webhook_ids_falls_back_to_unknown_on_malformed_payload() -> None:
    ids = extract_webhook_ids(b"not json")

    assert ids.event_id == "unknown"
    assert ids.delivery_id == "unknown"
