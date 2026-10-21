"""A member's alert (TEC-1845): save, pause, resume and stop. A member's
address is proved, so the alert is on at once."""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

CRITERIA = dict(age_min=26, age_max=34, countries=[], regions=[], relocations=[], torah_levels=[],
                shabbats=[], calendars=[], wants_children=None)


@pytest.fixture
def member(make_person, sign_in):
    p = make_person(name='Miriam Levi', gender='Woman')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=p['id']))
        tx.execute('INSERT INTO search_preference_age (person_id, min_age, max_age) VALUES (%(i)s, 26, 34) '
                   'ON CONFLICT (person_id) DO UPDATE SET min_age = 26, max_age = 34', dict(i=p['id']))
    return dict(p, headers=sign_in(p))


def _alert_row(person_id):
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM match_alert WHERE person_id = %(p)s', dict(p=person_id)).fetchone()
    return dict(row) if row else None


def _put(client, member, criteria=None, **flags):
    return client.put('/matchmaker/alert', headers=member['headers'],
                      json=dict(criteria=criteria or CRITERIA, notify_push=flags.get('push', True),
                                notify_email=flags.get('email', True)))


def test_no_alert_offers_the_saved_age_band(client, member):
    r = client.get('/matchmaker/alert', headers=member['headers'])
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'alert': None, 'defaults': {'age_min': 26, 'age_max': 34}}


def test_saving_turns_it_on_and_says_so(client, member):
    r = _put(client, member, push=False)
    assert r.status_code == 200, r.get_data(as_text=True)
    alert = r.get_json()['alert']
    assert alert['state'] == 'on' and alert['summary'] == 'Ages 26 to 34, anywhere.'
    assert alert['notify_push'] is False and alert['notify_email'] is True
    assert alert['criteria'] == CRITERIA
    row = _alert_row(member['id'])
    assert row['confirmed_at'] is not None and row['stop_token_hash'] and row['lead_id'] is None


def test_saving_again_keeps_the_count_window(client, member):
    _put(client, member)
    first = _alert_row(member['id'])
    _put(client, member, dict(CRITERIA, age_max=40))
    again = _alert_row(member['id'])
    assert again['id'] == first['id'] and again['counted_since'] == first['counted_since']
    assert again['stop_token_hash'] == first['stop_token_hash'] and again['criteria']['age_max'] == 40


def test_pausing_keeps_what_you_are_looking_for(client, member):
    _put(client, member, dict(CRITERIA, shabbats=['saturday-only']))
    r = client.post('/matchmaker/alert/pause', headers=member['headers'])
    assert r.status_code == 200 and r.get_json()['alert']['state'] == 'paused'
    assert r.get_json()['alert']['criteria']['shabbats'] == ['saturday-only']
    assert _alert_row(member['id'])['paused_at'] is not None
    r = client.post('/matchmaker/alert/resume', headers=member['headers'])
    assert r.get_json()['alert']['state'] == 'on' and _alert_row(member['id'])['paused_at'] is None


def test_stopping_deletes_it(client, member):
    _put(client, member)
    r = client.delete('/matchmaker/alert', headers=member['headers'])
    assert r.status_code == 200 and r.get_json()['alert'] is None
    assert _alert_row(member['id']) is None


def test_pausing_with_no_alert_is_not_found(client, member):
    r = client.post('/matchmaker/alert/pause', headers=member['headers'])
    assert r.status_code == 404 and r.get_json()['error'] == 'no_alert'


def test_a_bad_criterion_says_which(client, member):
    r = _put(client, member, dict(CRITERIA, polygyny=['open']))
    assert r.status_code == 400 and r.get_json() == {'error': 'bad_criteria', 'field': 'polygyny'}
    assert _alert_row(member['id']) is None


def test_closed_until_its_switch(client, member, monkeypatch):
    monkeypatch.delenv('AHAVAH_MATCHMAKER_ALERTS_ENABLED')
    h = member['headers']
    for r in (client.get('/matchmaker/alert', headers=h), _put(client, member),
              client.post('/matchmaker/alert/pause', headers=h),
              client.post('/matchmaker/alert/resume', headers=h),
              client.delete('/matchmaker/alert', headers=h)):
        assert r.status_code == 404
    monkeypatch.setenv('AHAVAH_MATCHMAKER_ALERTS_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert client.get('/matchmaker/alert', headers=h).status_code == 404


def test_an_onboardee_has_no_alert(client, tool_visitor):
    _email, h = tool_visitor()
    assert client.get('/matchmaker/alert', headers=h).status_code == 401
