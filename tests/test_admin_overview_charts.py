"""The Overview's charts and sparklines, after the 13 Oct 2026 health review.

Three defects, each about a chart saying something its data does not:

1. The empty state could never show. Every series is a generate_series of
   days, so it always had 30 or 7 rows, and the admin's `length === 0`
   check was never true: Premium adds drew 30 zero-height bars rather than
   "New Premium subscriptions plot here". A series with nothing in it now
   arrives empty.

2. Premium adds counted test-mode Stripe events. Paying members already
   required a live event; the chart did not, so one test checkout would
   have plotted as a sale. All 23 purchase events on file in production
   were test mode.

3. Sparklines plotted other series: Total persons and Active 24h both drew
   daily sign-ups. Total persons now has its own series, members_30d, the
   running count of members by the end of each Barbados day.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

import pytest

from database import api_tx
from service.admin.queries import Q_OVERVIEW_PREMIUM_30D
from service.admin.queries.overview import Q_OVERVIEW_MEMBERS_30D, Q_OVERVIEW_SIGNUPS_30D


def _series(sql: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(sql).fetchall()]


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='ChartsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _purchase(person_id: int, payload: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s, %(pl)s::jsonb,
                       ((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '09:00')
                       AT TIME ZONE 'America/Barbados')""",
            dict(eid=f'test-charts-{uuid.uuid4()}', uid=str(person_id), pl=payload))


# ---------------------------------------------------------------------------
# 1. The empty state
# ---------------------------------------------------------------------------

def test_a_series_with_nothing_in_it_arrives_empty():
    from service.api.admin.overview_routes import _empty_when_nothing
    zeros = [dict(day='2026-10-12', adds=0), dict(day='2026-10-13', adds=0)]
    assert _empty_when_nothing(zeros, ('adds',)) == []
    one = [dict(day='2026-10-12', adds=0), dict(day='2026-10-13', adds=1)]
    assert _empty_when_nothing(one, ('adds',)) == one, 'a series with any value keeps every day'


def test_the_route_never_sends_a_chart_of_only_zeros(client, admin_headers):
    """Whatever the shared test database holds, each chart the Overview
    sends is either empty or has something on it, and a non-empty one keeps
    every day so the x axis is whole."""
    body = client.get('/admin/overview', headers=admin_headers).get_json()
    for key, values, days in (('signups_30d', ('waitlist', 'beta', 'person'), 30),
                              ('referral_ctr_7d', ('clicks', 'signups'), 7),
                              ('premium_30d', ('adds',), 30),
                              ('members_30d', ('total',), 30)):
        series = body[key]
        if series:
            assert len(series) == days, key
            assert any(row[v] for row in series for v in values), f'{key} is all zeros'


# ---------------------------------------------------------------------------
# 2. Premium adds are live Stripe events
# ---------------------------------------------------------------------------

def test_a_test_mode_checkout_is_not_a_premium_add(make_person):
    p = make_person(name='TestModeBuyer')
    before = _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds']
    _purchase(p['id'], '{"livemode": false}')
    _purchase(p['id'], '{}')
    assert _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds'] == before, 'a test-mode event plotted as a sale'


def test_a_live_checkout_is_a_premium_add_wherever_livemode_sits(make_person):
    """The same rule as paying_members: `livemode` on the event, or on the
    event object when the payload is stored as the object itself."""
    p = make_person(name='LiveBuyer')
    before = _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds']
    _purchase(p['id'], '{"livemode": true, "data": {"object": {"mode": "subscription"}}}')
    _purchase(p['id'], '{"data": {"object": {"livemode": true, "mode": "subscription"}}}')
    assert _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds'] == before + 2


def test_paying_members_and_premium_adds_share_one_livemode_rule():
    from service.admin.queries.overview import Q_OVERVIEW_KPIS, live_stripe_event
    assert live_stripe_event('e') in Q_OVERVIEW_KPIS
    assert live_stripe_event('e') in Q_OVERVIEW_PREMIUM_30D


# ---------------------------------------------------------------------------
# 3. Total persons has its own series
# ---------------------------------------------------------------------------

def test_members_series_is_a_running_total_by_barbados_day(make_person):
    series0 = _series(Q_OVERVIEW_MEMBERS_30D)
    assert [r['day'] for r in series0] == [r['day'] for r in _series(Q_OVERVIEW_SIGNUPS_30D)]

    p = make_person(name='TenDaysIn')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET sign_up_time =
                 ((NOW() AT TIME ZONE 'America/Barbados')::date - 10 + TIME '12:00')
                 AT TIME ZONE 'America/Barbados'
               WHERE id = %(i)s""",
            dict(i=p['id']))
    series1 = _series(Q_OVERVIEW_MEMBERS_30D)
    moved = [b['total'] - a['total'] for a, b in zip(series0, series1)]
    assert moved == [0] * 19 + [1] * 11, 'the member counts from the day they joined onwards'


def test_staff_are_not_in_the_members_series(make_person):
    before = _series(Q_OVERVIEW_MEMBERS_30D)[-1]['total']
    p = make_person(name='StaffNotInSeries')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    assert _series(Q_OVERVIEW_MEMBERS_30D)[-1]['total'] == before
