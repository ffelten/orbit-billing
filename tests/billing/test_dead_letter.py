from datetime import UTC, datetime

import asyncpg

from orbit.billing.dead_letter import list_dead_letters, record_dead_letter

PERIOD_START = datetime(2026, 1, 1, tzinfo=UTC)


async def test_record_dead_letter_persists_the_delivery(db_conn: asyncpg.Connection) -> None:
    payload = b'{"id": "evt_1", "delivery_id": "dlv_1", "type": "charge.succeeded"}'

    await record_dead_letter(
        db_conn,
        provider_event_id="evt_1",
        delivery_id="dlv_1",
        payload=payload,
        error_message="connection lost",
        attempts=5,
    )

    entries = await list_dead_letters(db_conn)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider_event_id == "evt_1"
    assert entry.delivery_id == "dlv_1"
    assert entry.error_message == "connection lost"
    assert entry.attempts == 5
    assert entry.payload == {"id": "evt_1", "delivery_id": "dlv_1", "type": "charge.succeeded"}


async def test_record_dead_letter_survives_undecodable_payload(
    db_conn: asyncpg.Connection,
) -> None:
    await record_dead_letter(
        db_conn,
        provider_event_id="evt_bad",
        delivery_id="dlv_bad",
        payload=b"not json",
        error_message="malformed",
        attempts=5,
    )

    entries = await list_dead_letters(db_conn)
    assert entries[0].payload == {"raw": "not json"}


async def test_list_dead_letters_orders_most_recently_failed_first(
    db_conn: asyncpg.Connection,
) -> None:
    await record_dead_letter(
        db_conn,
        provider_event_id="evt_1",
        delivery_id="dlv_1",
        payload=b'{"id": "evt_1"}',
        error_message="first",
        attempts=5,
    )
    await record_dead_letter(
        db_conn,
        provider_event_id="evt_2",
        delivery_id="dlv_2",
        payload=b'{"id": "evt_2"}',
        error_message="second",
        attempts=5,
    )

    entries = await list_dead_letters(db_conn)

    assert [entry.provider_event_id for entry in entries] == ["evt_2", "evt_1"]


async def test_list_dead_letters_empty_by_default(db_conn: asyncpg.Connection) -> None:
    assert await list_dead_letters(db_conn) == []
