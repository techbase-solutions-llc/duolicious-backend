"""Every admin tab puts a moment on the same calendar day: Barbados's.

On 13 Oct 2026 at 08:56 Barbados the Overview said 1 sign-up today and the
System tab said 3. Persons 130 and 131 joined at 01:33 and 01:40 UTC, which
was 21:33 and 21:40 the evening before in Barbados. Overview already
bucketed by Barbados day; System, Cohorts and Economy used CURRENT_DATE and
`::date`, which are UTC days because the database session runs in UTC. Any
moment between 20:00 and midnight Barbados (midnight to 04:00 UTC) landed on
different days on different tabs.

The rows below sit either side of midnight UTC, and the assertions are
split in two so that a UTC rule fails whatever the time of day the suite
runs:

- 21:30 yesterday in Barbados is 01:30 UTC today. Before 20:00 Barbados the
  UTC date is the Barbados date, so a UTC rule calls this row today.
- 19:30 and 22:00 today in Barbados are 23:30 UTC today and 02:00 UTC
  tomorrow. After 20:00 Barbados the UTC date is already tomorrow, so a UTC
  rule calls the 19:30 row yesterday; before 20:00 it calls the 22:00 row
  tomorrow. Either way it counts one of the two, not both.
"""
from __future__ import annotations

import uuid

import pytest

from database import api_tx
from service.admin.queries import (
    Q_LEDGER_KPIS, Q_REFERRALS_CLICK_STREAM_7D, Q_SYSTEM_HEALTH,
    Q_WAITLIST_KPIS, Q_WAITLIST_VELOCITY_30D)

# An absolute instant at a Barbados wall-clock time, `day` days from today.
_AT = ("(((NOW() AT TIME ZONE 'America/Barbados')::date + {day} + TIME '{t}')"
       " AT TIME ZONE 'America/Barbados')")
LAST_NIGHT = _AT.format(day=-1, t='21:30')
EARLY_EVENING = _AT.format(day=0, t='19:30')
LATE_EVENING = _AT.format(day=0, t='22:00')


def _one(sql: str, params: dict | None = None) -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(sql, params).fetchone())


def _series(sql: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(sql).fetchall()]


def _barbados_today() -> str:
    with api_tx('read committed') as tx:
        return tx.execute(
            "SELECT (NOW() AT TIME ZONE 'America/Barbados')::date::text AS d").fetchone()['d']


@pytest.fixture
def rows():
    """Writes rows at a chosen moment and removes them afterwards."""
    made: list[tuple[str, str, str]] = []

    def _waitlist(at: str) -> None:
        e = f'barbados-day-{uuid.uuid4().hex[:10]}@example.com'
        with api_tx() as tx:
            tx.execute(f"INSERT INTO waitlist_signup (email, created_at) VALUES (%(e)s, {at})",
                       dict(e=e))
        made.append(('waitlist_signup', 'email', e))

    def _beta(at: str) -> None:
        e = f'barbados-day-{uuid.uuid4().hex[:10]}@example.com'
        with api_tx() as tx:
            tx.execute(f"INSERT INTO beta_signup (email, created_at) VALUES (%(e)s, {at})",
                       dict(e=e))
        made.append(('beta_signup', 'email', e))

    def _click(at: str) -> None:
        with api_tx() as tx:
            i = tx.execute(
                f"""INSERT INTO referral_link_click (code, well_formed, created_at, user_agent_class)
                    VALUES ('barbadosday', TRUE, {at}, 'mobile') RETURNING id::text AS id""").fetchone()['id']
        made.append(('referral_link_click', 'id', i))

    yield dict(waitlist=_waitlist, beta=_beta, click=_click)

    with api_tx() as tx:
        for table, col, value in made:
            tx.execute(f"DELETE FROM {table} WHERE {col}::text = %(v)s", dict(v=value))


def _joins_at(make_person, at: str) -> dict:
    p = make_person(name='BarbadosDay')
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET sign_up_time = {at} WHERE id = %(i)s", dict(i=p['id']))
    return p


def _ledger_at(person_uuid: str, at: str, delta: int) -> None:
    with api_tx() as tx:
        tx.execute(
            f"""INSERT INTO token_ledger (person_id, delta, reason, created_at)
                VALUES (%(p)s::uuid, %(d)s, 'boost', {at})""",
            dict(p=person_uuid, d=delta))


# ---------------------------------------------------------------------------
# Single "today" figures
# ---------------------------------------------------------------------------

def test_system_signups_today_is_the_barbados_day(make_person):
    before = _one(Q_SYSTEM_HEALTH)['signups_today']
    _joins_at(make_person, LAST_NIGHT)
    assert _one(Q_SYSTEM_HEALTH)['signups_today'] == before, 'last night counted as today'
    _joins_at(make_person, EARLY_EVENING)
    _joins_at(make_person, LATE_EVENING)
    assert _one(Q_SYSTEM_HEALTH)['signups_today'] == before + 2


def test_waitlist_today_is_the_barbados_day(rows):
    before = _one(Q_WAITLIST_KPIS)['today']
    rows['waitlist'](LAST_NIGHT)
    assert _one(Q_WAITLIST_KPIS)['today'] == before, 'last night counted as today'
    rows['waitlist'](EARLY_EVENING)
    rows['waitlist'](LATE_EVENING)
    assert _one(Q_WAITLIST_KPIS)['today'] == before + 2


def test_ledger_today_net_is_the_barbados_day(make_person):
    p = make_person(name='BarbadosLedger')
    before = _one(Q_LEDGER_KPIS, dict(days=0))['today']
    _ledger_at(p['uuid'], LAST_NIGHT, 100)
    assert _one(Q_LEDGER_KPIS, dict(days=0))['today'] == before, 'last night counted as today'
    _ledger_at(p['uuid'], EARLY_EVENING, 7)
    _ledger_at(p['uuid'], LATE_EVENING, 5)
    assert _one(Q_LEDGER_KPIS, dict(days=0))['today'] == before + 12


# ---------------------------------------------------------------------------
# Day series: they end on the Barbados today, and each row lands on its
# Barbados day
# ---------------------------------------------------------------------------

def test_the_cohorts_series_end_on_the_barbados_day():
    today = _barbados_today()
    for sql in (Q_WAITLIST_VELOCITY_30D, Q_REFERRALS_CLICK_STREAM_7D):
        assert _series(sql)[-1]['day'] == today


def test_velocity_puts_each_row_on_its_barbados_day(make_person, rows):
    def bars():
        s = _series(Q_WAITLIST_VELOCITY_30D)
        return s[-2], s[-1]

    (y0, t0) = bars()
    _joins_at(make_person, LAST_NIGHT)
    rows['waitlist'](LAST_NIGHT)
    rows['beta'](LAST_NIGHT)
    (y1, t1) = bars()
    for col in ('person', 'waitlist', 'beta'):
        assert t1[col] == t0[col], f'{col}: last night counted as today'
        assert y1[col] == y0[col] + 1, f'{col}: last night missing from yesterday'

    _joins_at(make_person, EARLY_EVENING)
    _joins_at(make_person, LATE_EVENING)
    rows['waitlist'](EARLY_EVENING)
    rows['waitlist'](LATE_EVENING)
    rows['beta'](EARLY_EVENING)
    rows['beta'](LATE_EVENING)
    (_, t2) = bars()
    for col in ('person', 'waitlist', 'beta'):
        assert t2[col] == t1[col] + 2, f'{col}: this evening not all on today'


def test_click_stream_puts_each_click_on_its_barbados_day(rows):
    before = _series(Q_REFERRALS_CLICK_STREAM_7D)[-1]['mobile']
    rows['click'](LAST_NIGHT)
    assert _series(Q_REFERRALS_CLICK_STREAM_7D)[-1]['mobile'] == before
    rows['click'](EARLY_EVENING)
    rows['click'](LATE_EVENING)
    assert _series(Q_REFERRALS_CLICK_STREAM_7D)[-1]['mobile'] == before + 2


# ---------------------------------------------------------------------------
# One helper
# ---------------------------------------------------------------------------

def test_no_admin_query_buckets_by_the_utc_day():
    """CURRENT_DATE is the UTC date in this database. A standing guard, so a
    new query cannot quietly bring the split back."""
    import service.admin.queries as q
    for name in dir(q):
        if name.startswith('Q_'):
            sql = getattr(q, name)
            assert 'CURRENT_DATE' not in sql, f'{name} uses the UTC day'


def test_overview_reads_today_from_the_shared_helper():
    from service.admin.queries.days import BARBADOS_TODAY
    from service.admin.queries.overview import Q_OVERVIEW_SIGNUPS_30D
    assert BARBADOS_TODAY in Q_OVERVIEW_SIGNUPS_30D
