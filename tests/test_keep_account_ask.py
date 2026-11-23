"""Keep my account or continue deleting (TEC-2056; design "Ahavah Deletion
and Organiser Emails", section 1, owner decisions 11 Nov 2026).

With keep_account_ask on, a member who signs in while their account is set
to be deleted is asked before anything changes: the sign-in keeps the
deletion date, hides nothing new and moves no sign-in time, and /check-otp
names the date so the app can ask. "Keep my account" is POST
/account/cancel-deletion; "Continue deleting" is a sign-out, after which the
pendingdeletion cron deletes on the day. Off, signing in cancels the
deletion as before (tests/test_exit_answer.py covers that path).
"""
from __future__ import annotations

import pathlib
from uuid import uuid4

import pytest

from database import api_tx

ENV = 'AHAVAH_KEEP_ACCOUNT_ASK_ENABLED'
CLIENT = '45.33.20.12'


@pytest.fixture(autouse=True)
def exit_answer_cleanup():
    with api_tx() as tx:
        before = tx.execute('SELECT COALESCE(MAX(id), 0) AS m FROM exit_answer').fetchone()['m']
    yield
    with api_tx() as tx:
        tx.execute('DELETE FROM exit_answer WHERE id > %(m)s', dict(m=before))


@pytest.fixture
def ask_on(monkeypatch):
    monkeypatch.setenv(ENV, '1')


def _person(person) -> dict:
    with api_tx() as tx:
        return dict(tx.execute(
            """SELECT email, activated, deletion_requested_at, sign_in_time, sign_in_count
                 FROM person WHERE id = %(p)s""",
            dict(p=person['id'])).fetchone())


def _answers(note: str) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM exit_answer WHERE note = %(n)s ORDER BY id', dict(n=note)).fetchall()]


def _delete(client, sign_in, person, **kw):
    r = client.delete('/account', headers=sign_in(person), **kw)
    assert r.status_code == 200, r.get_data(as_text=True)


def _otp_sign_in(client, signup_env, email):
    """The real /request-otp and /check-otp. Returns (response, bearer)."""
    r = signup_env.request(email, ip=CLIENT)
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    ok = client.post('/check-otp', json=dict(email=email, otp='000000'),
                     headers={'Authorization': f'Bearer {token}'},
                     environ_base={'REMOTE_ADDR': CLIENT})
    return ok, {'Authorization': f'Bearer {token}'}


def _iso(t) -> str:
    from datetime import timezone
    return t.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --- the switch ---------------------------------------------------------------

def test_the_switch_is_off_by_default_and_in_the_compose_file(monkeypatch):
    from service.campaigns.switches import SWITCHES, enabled
    monkeypatch.delenv(ENV, raising=False)
    assert SWITCHES['keep_account_ask'] == ENV
    assert enabled('keep_account_ask') is False
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{ENV}: ${{{ENV}:-0}}') == 2


def test_off_signing_in_cancels_and_names_no_date(client, signup_env, sign_in, make_person,
                                                  monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    p = make_person(name='OffSwitch')
    _delete(client, sign_in, p)
    ok, _ = _otp_sign_in(client, signup_env, _person(p)['email'])
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.get_json()['deletion_requested_at'] is None
    row = _person(p)
    assert row['activated'] is True and row['deletion_requested_at'] is None


# --- on: the sign-in asks ---------------------------------------------------------

def test_on_signing_in_keeps_the_deletion_and_names_its_date(client, signup_env, sign_in,
                                                             make_person, ask_on):
    p = make_person(name='Asked')
    note = f'ask-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='break', note=note))
    before = _person(p)
    assert before['activated'] is False and before['deletion_requested_at'] is not None

    ok, _ = _otp_sign_in(client, signup_env, before['email'])

    assert ok.status_code == 200, ok.get_data(as_text=True)
    body = ok.get_json()
    assert body['onboarded'] is True
    assert body['deletion_requested_at'] == _iso(before['deletion_requested_at'])
    after = _person(p)
    assert after['activated'] is False, 'still hidden while the member decides'
    assert after['deletion_requested_at'] == before['deletion_requested_at']
    assert after['sign_in_time'] == before['sign_in_time'], 'the purge guard is not tripped'
    assert after['sign_in_count'] == before['sign_in_count'] + 1
    # The exit answer stays open (held) until the member chooses.
    [answer] = _answers(note)
    assert answer['kept_at'] is None and answer['person_id'] == p['id']


def test_on_a_member_with_no_deletion_signs_in_as_before(client, signup_env, make_person, ask_on):
    p = make_person(name='Ordinary')
    ok, _ = _otp_sign_in(client, signup_env, _person(p)['email'])
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.get_json()['deletion_requested_at'] is None
    row = _person(p)
    assert row['activated'] is True and row['deletion_requested_at'] is None


def test_on_keep_my_account_cancels_the_deletion_and_marks_the_answer_kept(
        client, signup_env, sign_in, make_person, ask_on):
    p = make_person(name='Keeper')
    note = f'keep-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='break', note=note))
    ok, bearer = _otp_sign_in(client, signup_env, _person(p)['email'])
    assert ok.status_code == 200
    signed_in_before = _person(p)['sign_in_time']

    r = client.post('/account/cancel-deletion', headers=bearer)

    assert r.status_code == 200 and r.get_json() == {'ok': True, 'restored': True}
    row = _person(p)
    assert row['activated'] is True and row['deletion_requested_at'] is None
    assert row['sign_in_time'] > signed_in_before, 'keeping the account counts as the sign-in'
    [answer] = _answers(note)
    assert answer['kept_at'] is not None and answer['person_id'] is None


def test_on_continue_deleting_signs_out_and_the_cron_still_deletes_on_the_day(
        client, signup_env, sign_in, make_person, ask_on):
    from service.cron.pendingdeletion import _Q_EXPIRED
    p = make_person(name='Leaver')
    note = f'leave-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='met_elsewhere', note=note))
    ok, bearer = _otp_sign_in(client, signup_env, _person(p)['email'])
    assert ok.status_code == 200
    asked = _person(p)

    out = client.post('/sign-out', headers=bearer)

    assert out.status_code == 200, out.get_data(as_text=True)
    row = _person(p)
    assert row['deletion_requested_at'] == asked['deletion_requested_at']
    assert row['activated'] is False
    [answer] = _answers(note)
    assert answer['kept_at'] is None, 'the answer stays held'
    # Eight days on, the cron's own query picks the member up.
    with api_tx() as tx:
        tx.execute("""UPDATE person
                         SET deletion_requested_at = deletion_requested_at - INTERVAL '8 days',
                             sign_in_time = sign_in_time - INTERVAL '8 days'
                       WHERE id = %(p)s""", dict(p=p['id']))
        ids = {r['id'] for r in tx.execute(_Q_EXPIRED, dict(days=7)).fetchall()}
    assert p['id'] in ids


def test_on_the_sign_in_never_counts_a_club_member_twice(client, signup_env, sign_in,
                                                         make_person, ask_on):
    """The club count goes up only when the sign-in makes the member
    visible again, which a kept deletion does not."""
    p = make_person(name='Clubbed')
    club = f'keepclub{uuid4().hex[:8]}'
    with api_tx() as tx:
        tx.execute('INSERT INTO club (name, count_members) VALUES (%(c)s, 1)', dict(c=club))
        tx.execute('INSERT INTO person_club (person_id, club_name) VALUES (%(p)s, %(c)s)',
                   dict(p=p['id'], c=club))
    try:
        _delete(client, sign_in, p)
        ok, _ = _otp_sign_in(client, signup_env, _person(p)['email'])
        assert ok.status_code == 200
        with api_tx() as tx:
            n = tx.execute('SELECT count_members FROM club WHERE name = %(c)s',
                           dict(c=club)).fetchone()['count_members']
        assert n == 1
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM person_club WHERE club_name = %(c)s', dict(c=club))
            tx.execute('DELETE FROM club WHERE name = %(c)s', dict(c=club))
