import asyncpg

from orbit.billing.charges import ChargeStatus
from orbit.billing.metrics import list_charge_outcomes_by_day, record_charge_outcome


async def test_record_charge_outcome_creates_a_counter(db_conn: asyncpg.Connection) -> None:
    await record_charge_outcome(db_conn, ChargeStatus.SUCCEEDED)

    daily = await list_charge_outcomes_by_day(db_conn)

    assert len(daily) == 1
    assert daily[0].succeeded == 1
    assert daily[0].failed == 0


async def test_record_charge_outcome_increments_same_day_counter(
    db_conn: asyncpg.Connection,
) -> None:
    await record_charge_outcome(db_conn, ChargeStatus.SUCCEEDED)
    await record_charge_outcome(db_conn, ChargeStatus.SUCCEEDED)
    await record_charge_outcome(db_conn, ChargeStatus.FAILED)

    daily = await list_charge_outcomes_by_day(db_conn)

    assert len(daily) == 1
    assert daily[0].succeeded == 2
    assert daily[0].failed == 1


async def test_list_charge_outcomes_empty_by_default(db_conn: asyncpg.Connection) -> None:
    assert await list_charge_outcomes_by_day(db_conn) == []
