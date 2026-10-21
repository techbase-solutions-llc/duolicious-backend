"""Overview and whoami, the API half of the admin audit's Medium findings
(TEC-1845, 21 Oct).

- `member_total` counts members as the Sources panel does (activated, not
  staff, not a test address). `person_total` keeps its meaning, which the
  audit-medium admin labels "Includes deactivated and test accounts".
- `recent_activity_all` adds reports and live Premium checkouts to the feed.
  `recent_activity` keeps its five kinds: both admins look each kind up in a
  fixed table and would fail on a new one.
- whoami sends the caller's roles."""
from __future__ import annotations

import json
from uuid import uuid4

from database import api_tx


def _overview(client, headers) -> dict:
    r = client.get('/admin/overview', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_member_total_leaves_out_a_deactivated_member(client, make_person, admin_headers):
    before = _overview(client, admin_headers)['kpis']
    gone = make_person(name='Gone')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=gone['id']))
    after = _overview(client, admin_headers)['kpis']
    assert after['person_total'] == before['person_total'] + 1
    assert after['member_total'] == before['member_total']
    make_person(name='Here')
    last = _overview(client, admin_headers)['kpis']
    assert last['member_total'] == before['member_total'] + 1


def test_a_report_appears_in_the_full_feed_only(client, make_person, admin_headers):
    reporter = make_person(name='Reporter')
    reported = make_person(name=f'Reported {uuid4().hex[:6]}')
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO person_report (reporter_id, reported_id, reported_at, reason)
               VALUES (%(a)s, %(b)s, NOW() AT TIME ZONE 'UTC' + INTERVAL '1 minute', 'spam')""",
            dict(a=reporter['id'], b=reported['id']))
    data = _overview(client, admin_headers)
    reports = [e for e in data['recent_activity_all'] if e['kind'] == 'report']
    assert reports and reports[0]['object'] == reported['uuid']
    assert reports[0]['subject'].startswith('Reported ')
    assert {e['kind'] for e in data['recent_activity']} <= {
        'signup_member', 'signup', 'signup_waitlist', 'referral_credited', 'admin_action'}


def test_a_live_premium_checkout_appears_in_the_full_feed(client, make_person, admin_headers):
    member = make_person(name=f'Payer {uuid4().hex[:6]}')
    event_id = f'evt_test_{uuid4().hex}'
    payload = {'livemode': True, 'data': {'object': {'mode': 'subscription'}}}
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(e)s, 'checkout.session.completed', %(p)s, %(j)s::jsonb,
                       NOW() + INTERVAL '1 minute')""",
            dict(e=event_id, p=str(member['id']), j=json.dumps(payload)))
    try:
        feed = _overview(client, admin_headers)['recent_activity_all']
        premium = [e for e in feed if e['kind'] == 'premium']
        assert premium and premium[0]['object'] == member['uuid']
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM entitlement_event WHERE event_id = %(e)s', dict(e=event_id))


def test_whoami_sends_the_roles(client, admin_headers):
    r = client.get('/admin/whoami', headers=admin_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body['is_admin'] is True
    assert body['roles'] == ['admin']
