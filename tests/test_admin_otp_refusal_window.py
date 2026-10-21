"""Sign-up code refusals: the total and Why refused read one window
(TEC-1845 admin audit, Minor 14).

The refused total sums Q_OTP_DAILY's 30 Barbados days, while Why refused
read a rolling NOW() - 30 days, so a refusal late on the Barbados day
before the series began counted in Why refused and not in the total. Both
now read the 30 Barbados days."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx
from service.admin.queries.system import Q_OTP_DAILY, Q_OTP_REFUSALS_30D


@pytest.fixture
def reason():
    r = f'test-minor-{uuid4().hex[:8]}'
    yield r
    with api_tx() as tx:
        tx.execute("DELETE FROM otp_request WHERE refused = %(r)s", dict(r=r))


def _refuse_at_barbados(reason: str, days_ago: int, local_time: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO otp_request (requested_at, new_address, refused)
               VALUES ((((NOW() AT TIME ZONE 'America/Barbados')::date
                          - %(d)s)::timestamp + %(t)s::time)
                         AT TIME ZONE 'America/Barbados', TRUE, %(r)s)""",
            dict(d=days_ago, t=local_time, r=reason))


def _reason_count(reason: str) -> int:
    with api_tx() as tx:
        rows = tx.execute(Q_OTP_REFUSALS_30D).fetchall()
    return next((int(r['count']) for r in rows if r['reason'] == reason), 0)


def _daily_refused() -> int:
    with api_tx() as tx:
        return sum(int(r['refused']) for r in tx.execute(Q_OTP_DAILY).fetchall())


def test_a_refusal_before_the_first_barbados_day_is_in_neither(reason):
    before = _daily_refused()
    # The last minute of the Barbados day before the series' first: under
    # 30 days ago by the clock, so the rolling window counted it.
    _refuse_at_barbados(reason, 30, '23:59:00')
    assert _daily_refused() == before
    assert _reason_count(reason) == 0


def test_a_refusal_on_the_first_barbados_day_is_in_both(reason):
    before = _daily_refused()
    _refuse_at_barbados(reason, 29, '00:00:30')
    assert _daily_refused() == before + 1
    assert _reason_count(reason) == 1
