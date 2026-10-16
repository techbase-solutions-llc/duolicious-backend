"""Members sign in exactly as before.

TEC-1848, docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md,
"What changes for members: nothing visible". Every rule of the free bot
protection is armed here against the member's own client address and
network: the hour's new-address limit spent, the network's five new
addresses used, a missing stamp refused, and DNS saying the member's
domain takes no mail. A member and an admin still get their code, sign in
with it, and leave no trace in the counters the rules keep.
"""
import pytest

from database import api_tx
import service.signupguard as guard

CLIENT = '45.33.20.9'


def _account(make_person, admin=False) -> str:
    p = make_person(name='Unaffected')
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                       dict(i=p['id']))
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=p['id'])).fetchone()['email']


def _counters(env) -> dict:
    return {
        key: (sorted(env.redis.smembers(key)) if env.redis.type(key) == 'set'
              else env.redis.get(key))
        for key in env.redis.scan_iter('signupguard:*')
    }


@pytest.fixture
def armed(signup_env, monkeypatch):
    # Five different new addresses from the member's own address: the hour's
    # limit and the network's five, both spent.
    for _ in range(5):
        r = signup_env.request(signup_env.new_email(), ip=CLIENT)
        assert signup_env.issued(r.get_json()['session_token'])
    monkeypatch.setattr(guard, 'STAMP_REQUIRED', True)
    signup_env.dns['gmail.com'] = False
    signup_env.dns['example.com'] = False
    # Proof the rules are live: a new address from here is refused.
    r = signup_env.request(signup_env.new_email(), ip=CLIENT)
    assert not signup_env.issued(r.get_json()['session_token'])
    assert signup_env.refusals() == ['stamp_missing']
    signup_env.sent.clear()
    return signup_env


@pytest.mark.parametrize('admin', [False, True], ids=['member', 'admin'])
@pytest.mark.parametrize('stamp', [None, 'forged.0000'], ids=['no stamp', 'forged stamp'])
def test_an_account_gets_its_code_and_signs_in_with_every_rule_armed(
        client, armed, make_person, admin, stamp):
    email = _account(make_person, admin=admin)
    before = _counters(armed)
    body = {} if stamp is None else {'signup_stamp': stamp}

    r = armed.request(email, ip=CLIENT, **body)

    assert r.status_code == 200, r.get_data(as_text=True)
    assert set(r.get_json()) == {'session_token'}
    token = r.get_json()['session_token']
    assert armed.issued(token)
    assert armed.sent == [email]

    # A registered @example.com address is always given 000000.
    ok = client.post('/check-otp', json=dict(email=email, otp='000000'),
                     headers={'Authorization': f'Bearer {token}'},
                     environ_base={'REMOTE_ADDR': CLIENT})
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.get_json()['onboarded'] is True

    assert _counters(armed) == before
    assert armed.dns_calls.count('example.com') == 0
    assert armed.refusals() == ['stamp_missing']


@pytest.mark.parametrize('admin', [False, True], ids=['member', 'admin'])
def test_an_account_gets_every_resend_and_signs_in_with_every_rule_armed(
        client, armed, make_person, admin):
    """/resend-otp applies the new-address rules too (16 Oct 2026). A
    session for an existing account never reaches them: more resends than
    a new address may have in an hour all go out, and no counter moves."""
    email = _account(make_person, admin=admin)
    token = armed.request(email, ip=CLIENT).get_json()['session_token']
    before = _counters(armed)
    auth = {'Authorization': f'Bearer {token}'}

    for _ in range(guard.NEW_PER_CLIENT_HOUR + 1):
        r = client.post('/resend-otp', headers=auth, environ_base={'REMOTE_ADDR': CLIENT})
        assert r.status_code == 200, r.get_data(as_text=True)

    assert armed.sent == [email] * (guard.NEW_PER_CLIENT_HOUR + 2)
    ok = client.post('/check-otp', json=dict(email=email, otp='000000'),
                     headers=auth, environ_base={'REMOTE_ADDR': CLIENT})
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert _counters(armed) == before
    assert armed.dns_calls.count('example.com') == 0
    assert armed.refusals() == ['stamp_missing']


def test_a_wrong_code_is_still_just_a_wrong_code(client, armed, make_person):
    email = _account(make_person)
    token = armed.request(email, ip=CLIENT).get_json()['session_token']
    r = client.post('/check-otp', json=dict(email=email, otp='999999'),
                    headers={'Authorization': f'Bearer {token}'},
                    environ_base={'REMOTE_ADDR': CLIENT})
    assert r.status_code == 401
    assert r.get_data(as_text=True) == 'Invalid OTP'
