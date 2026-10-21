"""A visitor's alert (TEC-1845): ask, confirm by link, stop, and carried
into sign-up. A visitor is a lead with source alert:visitor."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')


@pytest.fixture
def visitor_email():
    made: list[str] = []

    def _new() -> str:
        address = f'hannah-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(address)
        return address

    yield _new
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _ask(client, email, **over):
    body = dict(email=email, looking_for='man', age_min=26, age_max=34, region='north-america',
                first_name='Hannah')
    body.update(over)
    return client.post('/alerts', json=body)


def _lead(email):
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT * FROM lead WHERE email = %(e)s AND source = 'alert:visitor'",
                         dict(e=email)).fetchone()
    return dict(row) if row else None


def _alert(email):
    with api_tx('read committed') as tx:
        row = tx.execute("""SELECT a.* FROM match_alert a JOIN lead l ON l.id = a.lead_id
                             WHERE l.email = %(e)s""", dict(e=email)).fetchone()
    return dict(row) if row else None


def _confirm_rows(email):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'mm_visitor_confirm' AND email = %(e)s ORDER BY id",
            dict(e=email)).fetchall()]


def _token(email) -> str:
    html = _confirm_rows(email)[-1]['payload']['html']
    return re.search(r'/alerts/confirm/([A-Za-z0-9_-]+)', html).group(1)


def test_a_visitor_asks_and_is_told_to_check_their_email(client, visitor_email):
    email = visitor_email()
    r = _ask(client, email)
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    assert r.headers['Cache-Control'] == 'no-store'
    [row] = _confirm_rows(email)
    assert row['lead_id'] is not None and 'a man aged 26 to 34 in North America' in row['payload']['html']
    assert 'Hello Hannah.' in row['payload']['html']
    lead = _lead(email)
    assert lead['source'] == 'alert:visitor' and lead['marketing_consent'] is False
    alert = _alert(email)
    assert alert['confirmed_at'] is None and alert['first_name'] == 'Hannah'
    assert alert['criteria'] == dict(looking_for='man', age_min=26, age_max=34, region='north-america')


def test_confirming_turns_it_on_and_confirms_the_lead(client, visitor_email):
    email = visitor_email()
    _ask(client, email)
    r = client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['state'] == 'confirmed' and len(body['stop_token']) == 32
    assert _alert(email)['confirmed_at'] is not None
    assert _lead(email)['confirmed_at'] is not None and _lead(email)['confirmed_via'] == 'link'


def test_the_link_used_again_says_already_on(client, visitor_email):
    email = visitor_email()
    _ask(client, email)
    token = _token(email)
    first = client.post('/alerts/confirm', json=dict(token=token)).get_json()
    again = client.post('/alerts/confirm', json=dict(token=token)).get_json()
    assert again == dict(state='already_on', stop_token=first['stop_token'])


def test_an_expired_link_says_so(client, visitor_email):
    email = visitor_email()
    _ask(client, email)
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET confirm_by = NOW() - interval '1 minute'
                       WHERE lead_id = (SELECT id FROM lead WHERE email = %(e)s)""", dict(e=email))
    r = client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert r.status_code == 410 and r.get_json()['error'] == 'expired'
    assert _alert(email)['confirmed_at'] is None


def test_an_unknown_link_is_not_found(client):
    r = client.post('/alerts/confirm', json=dict(token='x' * 32))
    assert r.status_code == 404 and r.get_json()['error'] == 'not_found'


def test_send_it_again_stops_after_3_and_says_nothing(client, visitor_email):
    """Past the limit nothing is sent, and the answer is a send's, so the
    form never tells anyone the address has an alert."""
    email = visitor_email()
    for _ in range(4):
        assert _ask(client, email).status_code == 201
    r = _ask(client, email)
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    assert len(_confirm_rows(email)) == 4 and _alert(email)['resends'] == 3


def _confirmed(client, email) -> dict:
    _ask(client, email)
    return client.post('/alerts/confirm', json=dict(token=_token(email))).get_json()


def test_asking_again_once_on_changes_nothing_until_the_link(client, visitor_email):
    """Anyone may type a visitor's address into the form: a confirmed alert
    changes only when its owner taps the new link (review, 21 Oct)."""
    email = visitor_email()
    first = _confirmed(client, email)
    r = _ask(client, email, region=None, age_max=40, first_name='Eve')
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    alert = _alert(email)
    assert alert['criteria']['region'] == 'north-america' and alert['criteria']['age_max'] == 34
    assert alert['first_name'] == 'Hannah' and alert['active'] is True
    assert len(_confirm_rows(email)) == 2
    assert 'a man aged 26 to 40' in _confirm_rows(email)[-1]['payload']['html']
    r = client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert r.status_code == 200 and r.get_json() == dict(state='confirmed', stop_token=first['stop_token'])
    alert = _alert(email)
    assert alert['criteria']['region'] is None and alert['criteria']['age_max'] == 40
    assert alert['first_name'] == 'Eve' and alert['pending_criteria'] is None
    again = client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert again.status_code == 404


def test_a_confirmed_alert_is_answered_as_a_new_address_is(client, visitor_email):
    on, fresh = visitor_email(), visitor_email()
    _confirmed(client, on)
    a, b = _ask(client, on, age_max=40), _ask(client, fresh)
    assert (a.status_code, a.get_json()['state']) == (b.status_code, b.get_json()['state'])
    assert set(a.get_json()) == set(b.get_json())


def test_a_change_request_leaves_the_original_link_saying_already_on(client, visitor_email):
    email = visitor_email()
    _ask(client, email)
    original = _token(email)
    stop = client.post('/alerts/confirm', json=dict(token=original)).get_json()['stop_token']
    _ask(client, email, age_max=40)
    assert client.post('/alerts/confirm', json=dict(token=original)).get_json() == dict(
        state='already_on', stop_token=stop)
    assert _alert(email)['criteria']['age_max'] == 34


def test_only_the_newest_change_link_applies(client, visitor_email):
    email = visitor_email()
    _confirmed(client, email)
    _ask(client, email, age_max=40)
    older = _token(email)
    _ask(client, email, age_max=45)
    assert client.post('/alerts/confirm', json=dict(token=older)).status_code == 404
    client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert _alert(email)['criteria']['age_max'] == 45


def test_an_expired_change_link_changes_nothing(client, visitor_email):
    email = visitor_email()
    _confirmed(client, email)
    _ask(client, email, age_max=40)
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET confirm_by = NOW() - interval '1 minute'
                       WHERE lead_id = (SELECT id FROM lead WHERE email = %(e)s)""", dict(e=email))
    r = client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert r.status_code == 410 and r.get_json()['error'] == 'expired'
    assert _alert(email)['criteria']['age_max'] == 34


def test_change_links_stop_after_3_more_and_say_nothing(client, visitor_email):
    email = visitor_email()
    _confirmed(client, email)
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET confirm_by = NULL, resends = 0
                       WHERE lead_id = (SELECT id FROM lead WHERE email = %(e)s)""", dict(e=email))
    for age in range(36, 40):
        assert _ask(client, email, age_max=age).status_code == 201
    r = _ask(client, email, age_max=44)
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    assert len(_confirm_rows(email)) == 1 + 4
    assert 'aged 26 to 39' in _confirm_rows(email)[-1]['payload']['html']
    # Once the last link has lapsed, a new ask sends again.
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET confirm_by = NOW() - interval '1 minute'
                       WHERE lead_id = (SELECT id FROM lead WHERE email = %(e)s)""", dict(e=email))
    assert _ask(client, email, age_max=44).status_code == 201
    assert len(_confirm_rows(email)) == 1 + 5


def test_a_visitor_who_used_every_resend_can_still_change_once_on(client, visitor_email):
    """The first confirm leaves its confirm_by and resends behind; they do
    not count against change links."""
    email = visitor_email()
    for _ in range(4):
        _ask(client, email)
    assert _alert(email)['resends'] == 3
    client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert _ask(client, email, age_max=40).status_code == 201
    assert len(_confirm_rows(email)) == 4 + 1
    client.post('/alerts/confirm', json=dict(token=_token(email)))
    assert _alert(email)['criteria']['age_max'] == 40


def test_stopping_deletes_a_visitor_alert(client, visitor_email):
    email = visitor_email()
    _ask(client, email)
    stop = client.post('/alerts/confirm', json=dict(token=_token(email))).get_json()['stop_token']
    r = client.post('/alerts/stop', json=dict(token=stop))
    assert r.status_code == 200 and r.get_json() == {'state': 'stopped'}
    assert _alert(email) is None
    assert client.post('/alerts/stop', json=dict(token=stop)).get_json() == {'state': 'stopped'}
    assert client.post('/alerts/stop', json=dict(token='y' * 32)).get_json() == {'state': 'stopped'}


def test_a_members_stop_link_turns_only_the_email_off(client, make_person, sign_in):
    from service.matchmaker.alerts import stop_token
    p = make_person(name='Miriam')
    h = sign_in(p)
    client.put('/matchmaker/alert', headers=h, json=dict(criteria=dict(age_min=26, age_max=34)))
    with api_tx('read committed') as tx:
        aid = tx.execute('SELECT id FROM match_alert WHERE person_id = %(p)s', dict(p=p['id'])).fetchone()['id']
    assert client.post('/alerts/stop', json=dict(token=stop_token(aid))).get_json() == {'state': 'stopped'}
    alert = client.get('/matchmaker/alert', headers=h).get_json()['alert']
    assert alert['notify_email'] is False and alert['state'] == 'on'


def test_a_members_address_writes_nothing_and_answers_the_same(client, make_person):
    email = f'member-{uuid4().hex[:8]}@ahavah-test.invalid'
    make_person(name='Member', email=email)
    r = _ask(client, email)
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    assert _lead(email) is None and _confirm_rows(email) == []


def test_a_refused_address_is_answered_as_a_send(client, visitor_email, monkeypatch):
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: 'honeypot')
    email = visitor_email()
    r = _ask(client, email, website='http://spam.example')
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': email}
    assert _lead(email) is None and _confirm_rows(email) == []


@pytest.mark.parametrize('over,field', [
    (dict(region='mars'), 'region'), (dict(age_min=17), 'age_min'), (dict(age_min=40, age_max=30), 'age_min'),
])
def test_a_bad_region_or_age_is_refused(client, visitor_email, over, field):
    r = _ask(client, visitor_email(), **over)
    assert r.status_code == 400 and r.get_json() == {'error': 'bad_criteria', 'field': field}


def test_a_bad_email_is_refused(client):
    r = _ask(client, 'not-an-address')
    assert r.status_code == 400 and r.get_json()['error'] == 'bad_email'


def test_a_visitor_who_joins_keeps_their_alert_as_a_member(client, visitor_email, finish_onboarding):
    email = visitor_email()
    _ask(client, email)
    client.post('/alerts/confirm', json=dict(token=_token(email)))
    r, pid = finish_onboarding(email=email)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        alert = dict(tx.execute('SELECT * FROM match_alert WHERE person_id = %(p)s', dict(p=pid)).fetchone())
    assert alert['lead_id'] is None and alert['notify_push'] is False and alert['notify_email'] is True
    assert alert['criteria']['regions'] == ['north-america'] and alert['criteria']['age_min'] == 26
    assert alert['criteria']['countries'] == []


def test_an_unconfirmed_alert_is_not_carried(client, visitor_email, finish_onboarding):
    email = visitor_email()
    _ask(client, email)
    _r, pid = finish_onboarding(email=email)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM match_alert WHERE person_id = %(p)s', dict(p=pid)).fetchone() is None


def test_closed_until_its_switch(client, visitor_email, monkeypatch):
    monkeypatch.delenv('AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED')
    email = visitor_email()
    assert _ask(client, email).status_code == 404
    assert client.post('/alerts/confirm', json=dict(token='x' * 32)).status_code == 404
    assert client.post('/alerts/stop', json=dict(token='x' * 32)).status_code == 200
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert client.post('/alerts/stop', json=dict(token='x' * 32)).status_code == 404


def test_the_confirm_email_waits_for_its_switch(client, visitor_email, monkeypatch):
    monkeypatch.delenv('AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED')
    email = visitor_email()
    assert _ask(client, email).status_code == 201
    assert _confirm_rows(email) == []
