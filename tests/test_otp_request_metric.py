"""Admin > System: sign-in codes requested and never entered, per day.

TEC-1848, item 6 of docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
The bot-protection plan works if the never-entered line for new addresses
falls. Each /request-otp that issues a code writes one otp_request row,
split into new addresses (no account) and existing ones; /check-otp marks
it entered. A request the server refuses without saying so (the honeypot,
and the rules that follow it) is counted apart from the codes, never as a
code that went unentered, or the line could not fall.

No address is stored: the row holds whether the address was new, the
session it opened and when that session was signed in.
"""
from datetime import date

import pytest

from database import api_tx


@pytest.fixture
def admin_headers(make_person, sign_in):
    p = make_person(name='OtpMetricAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return sign_in(p)


def _health(client, headers):
    r = client.get('/admin/system/health', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _today(client, headers):
    return _health(client, headers)['otp_daily'][-1]


def _member_email(make_person):
    p = make_person(name='OtpMetricMember')
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=p['id'])).fetchone()['email']


def test_the_day_list_is_thirty_barbados_days_ending_today(client, admin_headers):
    days = _health(client, admin_headers)['otp_daily']
    assert len(days) == 30
    parsed = [date.fromisoformat(d['day']) for d in days]
    assert parsed == sorted(parsed)
    assert set(days[0]) == {
        'day', 'new_requested', 'new_never_entered',
        'existing_requested', 'existing_never_entered', 'refused'}


def test_a_new_address_that_never_enters_its_code_is_counted(client, admin_headers, signup_env):
    before = _today(client, admin_headers)
    r = signup_env.request(signup_env.new_email())
    assert r.status_code == 200
    assert signup_env.issued(r.get_json()['session_token'])
    after = _today(client, admin_headers)
    assert after['new_requested'] == before['new_requested'] + 1
    assert after['new_never_entered'] == before['new_never_entered'] + 1
    assert after['existing_requested'] == before['existing_requested']


def test_a_member_who_enters_the_code_leaves_the_never_entered_line(
        client, admin_headers, signup_env, make_person):
    email = _member_email(make_person)
    before = _today(client, admin_headers)
    r = signup_env.request(email)
    token = r.get_json()['session_token']
    # A registered @example.com address is always given 000000 (the OTP CTE).
    ok = client.post('/check-otp', json=dict(email=email, otp='000000'),
                     headers={'Authorization': f'Bearer {token}'})
    assert ok.status_code == 200, ok.get_data(as_text=True)
    after = _today(client, admin_headers)
    assert after['existing_requested'] == before['existing_requested'] + 1
    assert after['existing_never_entered'] == before['existing_never_entered']
    assert after['new_requested'] == before['new_requested']


def test_a_member_who_does_not_enter_the_code_is_counted_as_existing(
        client, admin_headers, signup_env, make_person):
    email = _member_email(make_person)
    before = _today(client, admin_headers)
    signup_env.request(email)
    after = _today(client, admin_headers)
    assert after['existing_never_entered'] == before['existing_never_entered'] + 1
    assert after['new_never_entered'] == before['new_never_entered']


def test_a_honeypot_hit_is_refused_counted_and_looks_like_success(
        client, admin_headers, signup_env):
    before = _health(client, admin_headers)
    r = signup_env.request(signup_env.new_email(), website='https://spam.example')
    assert r.status_code == 200
    token = r.get_json()['session_token']
    assert isinstance(token, str) and len(token) == 128
    assert not signup_env.issued(token)
    assert signup_env.sent == []
    after = _health(client, admin_headers)
    assert after['otp_daily'][-1]['refused'] == before['otp_daily'][-1]['refused'] + 1
    # A refusal is not a code that went unentered.
    assert after['otp_daily'][-1]['new_never_entered'] == before['otp_daily'][-1]['new_never_entered']
    reasons = {r['reason']: r['count'] for r in after['otp_refusals_30d']}
    old = {r['reason']: r['count'] for r in before['otp_refusals_30d']}
    assert reasons.get('honeypot', 0) == old.get('honeypot', 0) + 1
