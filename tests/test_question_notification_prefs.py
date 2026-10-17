"""The quick questions push setting, the time zone and push taps (TEC-1845).

`questions` is a push-only event kind, on by default (owner decision of
16 Oct). Turning it off is stamped so switch-offs can be counted by week
(the guard rail). A subscription keeps its device's time zone for 18:00
local pushes; anything the server cannot read is stored as none. A landing
from a question push writes one push_tap, however often the page reloads.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')


def _member(make_person, sign_in, name):
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def _pref(pid):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT push_questions, push_questions_off_at FROM notification_preference '
                          'WHERE person_id = %(p)s', dict(p=pid)).fetchone()


def _subscribe(client, headers, endpoint, **extra):
    return client.post('/notifications/subscribe', headers=headers, json=dict(
        endpoint=endpoint, keys=dict(p256dh='k', auth='a'), **extra))


def _tz(pid):
    with api_tx('read committed') as tx:
        return [r['tz'] for r in tx.execute('SELECT tz FROM push_subscription WHERE person_id = %(p)s',
                                            dict(p=pid)).fetchall()]


def test_quick_question_pushes_are_on_by_default(client, make_person, sign_in):
    from service.notifications import _allowed_for_event
    me = _member(make_person, sign_in, 'PrefDefault')
    assert client.get('/notifications/preferences', headers=me['headers']).get_json()['push_questions'] is True
    assert _allowed_for_event(me['id'], 'questions') is True


def test_turning_it_off_is_stamped_and_turning_it_on_clears_it(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'PrefOff')
    assert client.patch('/notifications/preferences', headers=me['headers'],
                        json=dict(push_questions=False)).status_code == 204
    first = _pref(me['id'])
    assert first['push_questions'] is False and first['push_questions_off_at'] is not None
    client.patch('/notifications/preferences', headers=me['headers'], json=dict(push_questions=False))
    assert _pref(me['id'])['push_questions_off_at'] == first['push_questions_off_at']
    client.patch('/notifications/preferences', headers=me['headers'], json=dict(push_questions=True))
    assert _pref(me['id']) == dict(push_questions=True, push_questions_off_at=None)


def test_quick_questions_are_never_emailed():
    from service.campaigns import _Q_UNSUBSCRIBED
    from service.notifications import _EMAIL_COLUMN, _EMAIL_DEFAULTS
    assert _EMAIL_COLUMN['questions'] == 'push_questions'
    assert _EMAIL_DEFAULTS['questions'] is False
    assert 'push_questions' not in _Q_UNSUBSCRIBED['notifications']


def test_a_subscription_keeps_its_devices_time_zone(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TzKeep')
    endpoint = f'https://push.example.com/{uuid4()}'
    assert _subscribe(client, me['headers'], endpoint, tz='America/Chicago').status_code == 200
    _subscribe(client, me['headers'], endpoint)
    assert _tz(me['id']) == ['America/Chicago']


def test_a_bad_or_missing_time_zone_is_stored_as_none(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TzBad')
    for tz in ('Mars/Olympus_Mons', 'x' * 200, '', None):
        r = _subscribe(client, me['headers'], f'https://push.example.com/{uuid4()}', tz=tz)
        assert r.status_code == 200, tz
    assert _tz(me['id']) == [None, None, None, None]


def test_a_push_tap_is_recorded_once_per_10_minutes(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'Tapper')
    for src in ('qpush', 'qpush', 'lpush'):
        assert client.post('/push-taps', headers=me['headers'], json=dict(src=src)).status_code == 204
    with api_tx('read committed') as tx:
        rows = tx.execute('SELECT src FROM push_tap WHERE person_id = %(p)s ORDER BY id',
                          dict(p=me['id'])).fetchall()
    assert [r['src'] for r in rows] == ['qpush', 'lpush']


def test_an_unknown_source_is_refused(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TapBad')
    assert client.post('/push-taps', headers=me['headers'], json=dict(src='email')).status_code == 400


def test_a_signed_out_tap_is_refused(client):
    assert client.post('/push-taps', json=dict(src='qpush')).status_code == 400
