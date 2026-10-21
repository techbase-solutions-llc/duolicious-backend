"""Economy, the API half of the admin audit's Medium findings (TEC-1845,
21 Oct).

Subscriptions: expire_stale nulls subscription_expires_at once it passes,
so 'expired' (expiry < NOW() with a Stripe customer) could only count rows
in the gap before the nightly cron, and a lapsed subscriber's row read
'never'. A member with a live Stripe subscription event on file who is not
active now is expired, and the row says so (`ever_subscribed`).

Holders: each carries `founding` (the early-member Premium at sign-up, or
the founding_member entitlement) and `source`: 'stripe' (a live Stripe
subscription, Premium only), 'admin' (granted from the drawer), 'signup'
(the early-member grant) or 'unknown'."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from database import api_tx
from service.admin.queries.economy import (
    Q_ENTITLEMENT_HOLDERS, Q_SUBSCRIPTIONS_KPIS, Q_SUBSCRIPTIONS_ROWS)
from service.tokens import credit


@pytest.fixture
def events():
    made: list[str] = []

    def _event(person_id: int, event_type='checkout.session.completed', live=True):
        eid = f'evt_audit_{uuid4().hex}'
        payload = {'livemode': live, 'data': {'object': {'mode': 'subscription'}}}
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload)
                   VALUES (%(e)s, %(t)s, %(p)s, %(j)s::jsonb)""",
                dict(e=eid, t=event_type, p=str(person_id), j=json.dumps(payload)))
        made.append(eid)

    yield _event
    with api_tx() as tx:
        tx.execute('DELETE FROM entitlement_event WHERE event_id = ANY(%(e)s)', dict(e=made))


def _kpis() -> dict:
    with api_tx() as tx:
        return dict(tx.execute(Q_SUBSCRIPTIONS_KPIS).fetchone())


def _sub_row(uuid: str) -> dict:
    unlimited = Q_SUBSCRIPTIONS_ROWS.replace('LIMIT 200', 'LIMIT 1000000')
    with api_tx() as tx:
        return next(dict(r) for r in tx.execute(unlimited).fetchall() if r['person_uuid'] == uuid)


def test_a_lapsed_subscriber_counts_as_expired(make_person, events):
    before = _kpis()['expired']
    p = make_person(name='Lapsed')
    with api_tx() as tx:
        tx.execute("""UPDATE person SET stripe_customer_id = %(c)s, entitlements = '{}',
                             subscription_expires_at = NULL WHERE id = %(i)s""",
                   dict(c=f'cus_{uuid4().hex[:12]}', i=p['id']))
    events(p['id'])
    assert _kpis()['expired'] == before + 1
    row = _sub_row(p['uuid'])
    assert row['status'] == 'expired' and row['ever_subscribed'] is True


def test_a_test_mode_checkout_is_not_a_subscription(make_person, events):
    before = _kpis()['expired']
    p = make_person(name='TestMode')
    with api_tx() as tx:
        tx.execute("UPDATE person SET stripe_customer_id = %(c)s, subscription_expires_at = NULL "
                   "WHERE id = %(i)s", dict(c=f'cus_{uuid4().hex[:12]}', i=p['id']))
    events(p['id'], live=False)
    assert _kpis()['expired'] == before
    row = _sub_row(p['uuid'])
    assert row['status'] == 'never' and row['ever_subscribed'] is False


def _holder(name: str, uuid: str) -> dict:
    unlimited = Q_ENTITLEMENT_HOLDERS.replace('LIMIT 200', 'LIMIT 1000000')
    with api_tx() as tx:
        return next(dict(r) for r in tx.execute(
            unlimited, dict(name=name, expires_within_days=0)).fetchall() if r['person_uuid'] == uuid)


def _premium(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE person SET entitlements = ARRAY['premium']::TEXT[],
                             subscription_expires_at = NOW() + INTERVAL '30 days' WHERE id = %(i)s""",
                   dict(i=person_id))


def test_a_holder_from_the_sign_up_offer_is_founding(make_person):
    p = make_person(name='Early')
    _premium(p['id'])
    with api_tx() as tx:
        credit(tx, p['uuid'], 30, reason='subscription_stipend',
               metadata={'source': 'founding_member_starter'})
    row = _holder('premium', p['uuid'])
    assert (row['founding'], row['source']) == (True, 'signup')


def test_a_holder_granted_from_the_drawer_is_admin(make_person):
    p = make_person(name='Granted')
    _premium(p['id'])
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO admin_audit_log (actor_email, actor_uuid, action, target_uuid, metadata)
               VALUES ('owner@example.com', gen_random_uuid(), 'grant_entitlement', %(u)s::uuid,
                       '{"name": "premium"}'::jsonb)""", dict(u=p['uuid']))
    try:
        row = _holder('premium', p['uuid'])
        assert (row['founding'], row['source']) == (False, 'admin')
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid', dict(u=p['uuid']))


def test_a_paying_holder_is_stripe(make_person, events):
    p = make_person(name='Payer')
    _premium(p['id'])
    events(p['id'])
    assert _holder('premium', p['uuid'])['source'] == 'stripe'


def test_a_holder_with_nothing_on_file_is_unknown(make_person):
    p = make_person(name='Unknown')
    _premium(p['id'])
    assert _holder('premium', p['uuid'])['source'] == 'unknown'
