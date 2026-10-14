"""A signed page stamp catches sign-ups sent too fast.

TEC-1848, item 4 of docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
The sign-up page asks GET /signup-stamp for a signed timestamp when it
loads and sends it back as `signup_stamp` with /request-otp. A request for
an address with no account that comes under 2 seconds after its stamp, or
with a forged stamp, or one older than a day, is treated as a honeypot hit
is: answered as a send and nothing mailed.

A missing stamp is refused only once AHAVAH_SIGNUP_STAMP_REQUIRED is on,
which is set after the web that sends the stamp is live. Existing members
skip the stamp entirely, so an old web build never locks a member out.
"""
import pytest

from database import api_tx
import service.signupguard as guard


@pytest.fixture
def stamp(client, signup_env):
    def _stamp():
        r = client.get('/signup-stamp')
        assert r.status_code == 200, r.get_data(as_text=True)
        assert 'no-store' in r.headers.get('Cache-Control', '')
        return r.get_json()['stamp']
    return _stamp


def _code_issued(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    return env.issued(r.get_json()['session_token'])


def _refused_quietly(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    return isinstance(token, str) and len(token) == 128 and not env.issued(token)


def _member(make_person) -> str:
    p = make_person(name='StampMember')
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=p['id'])).fetchone()['email']


def _tamper(value: str) -> str:
    return value[:-1] + ('0' if value[-1] != '0' else '1')


def test_the_page_gets_a_stamp_signed_at_the_moment_it_asked(stamp):
    issued_ms, sig = stamp().split('.')
    assert int(issued_ms) == 1791946800000
    assert len(sig) == 64


def test_a_new_address_sent_two_seconds_after_the_stamp_gets_a_code(signup_env, stamp):
    s = stamp()
    signup_env.advance(2.5)
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email(), signup_stamp=s))


def test_a_new_address_sent_under_two_seconds_after_the_stamp_gets_no_code(signup_env, stamp):
    s = stamp()
    signup_env.advance(1.5)
    assert _refused_quietly(signup_env, signup_env.request(signup_env.new_email(), signup_stamp=s))
    assert signup_env.sent == []
    assert signup_env.refusals() == ['stamp_too_fast']


@pytest.mark.parametrize('forge', [
    _tamper,
    lambda s: f"{int(s.split('.')[0]) - 60000}.{s.split('.')[1]}",
    lambda s: 'not-a-stamp',
    lambda s: f"1791946800000.{'x' * 64}",
    lambda s: f"{s.split('.')[0]}.é{s.split('.')[1][1:]}",
])
def test_a_forged_stamp_gets_no_code(signup_env, stamp, forge):
    s = stamp()
    signup_env.advance(10)
    r = signup_env.request(signup_env.new_email(), signup_stamp=forge(s))
    assert _refused_quietly(signup_env, r)
    assert signup_env.refusals() == ['stamp_forged']


def test_a_stamp_older_than_a_day_gets_no_code(signup_env, stamp):
    s = stamp()
    signup_env.advance(86400 + 1)
    assert _refused_quietly(signup_env, signup_env.request(signup_env.new_email(), signup_stamp=s))
    assert signup_env.refusals() == ['stamp_expired']


def test_a_missing_stamp_is_let_through_until_the_switch_is_on(signup_env):
    assert guard.STAMP_REQUIRED is False
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email()))


def test_a_missing_stamp_gets_no_code_once_the_switch_is_on(signup_env, monkeypatch):
    monkeypatch.setattr(guard, 'STAMP_REQUIRED', True)
    assert _refused_quietly(signup_env, signup_env.request(signup_env.new_email()))
    assert signup_env.refusals() == ['stamp_missing']


def test_a_member_skips_the_stamp_entirely(signup_env, stamp, make_person, monkeypatch):
    monkeypatch.setattr(guard, 'STAMP_REQUIRED', True)
    member = _member(make_person)
    s = stamp()
    assert _code_issued(signup_env, signup_env.request(member))
    assert _code_issued(signup_env, signup_env.request(member, signup_stamp=s))
    assert _code_issued(signup_env, signup_env.request(member, signup_stamp=_tamper(s)))
    assert signup_env.sent == [member, member, member]
    assert signup_env.refusals() == []


def test_without_a_secret_no_stamp_is_issued_and_none_is_checked(
        signup_env, stamp, monkeypatch):
    monkeypatch.delenv('SESSION_TOKEN_SECRET', raising=False)
    monkeypatch.setattr(guard, 'STAMP_REQUIRED', True)
    assert stamp() is None
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email()))
    assert _code_issued(signup_env, signup_env.request(
        signup_env.new_email(), signup_stamp='not-a-stamp'))
