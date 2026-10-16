"""The new-address rules apply to /resend-otp too.

TEC-1848, docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
Until 16 Oct 2026 a resend was held only by the old shared OTP limits, so a
session for an address with no account could ask for a fresh code as often
as those allowed and the new-address limits never saw it. A resend for such
a session now counts against the same limits as /request-otp, and over a
limit it is answered exactly as a resend that went out, with nothing mailed
and the refusal recorded in otp_request.

The page stamp is not asked again: it belongs to the page load, which a
resend does not repeat, and the request that opened the session passed it.
Sessions of existing accounts are covered in test_signup_members_unaffected.
"""
from database import api_tx
import service.signupguard as guard

CLIENT = '45.33.30.4'
NETWORK = '45.33.30.'


def _session(env, email, ip=CLIENT) -> str:
    r = env.request(email, ip=ip)
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    assert env.issued(token)
    return token


def _resend(client, token, ip=CLIENT):
    return client.post('/resend-otp', headers={'Authorization': f'Bearer {token}'},
                       environ_base={'REMOTE_ADDR': ip})


def _issued_rows() -> int:
    with api_tx('read committed') as tx:
        return tx.execute("""SELECT count(*) AS n FROM otp_request
                              WHERE refused IS NULL AND requested_at > NOW() - interval '1 hour'""").fetchone()['n']


def test_a_resend_under_the_limits_is_sent_and_is_the_same_row(client, signup_env):
    email = signup_env.new_email()
    token = _session(signup_env, email)
    rows = _issued_rows()
    r = _resend(client, token)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert signup_env.sent == [email, email]
    assert _issued_rows() == rows, 'a resend on the same session is the same otp_request row'
    assert signup_env.refusals() == []


def test_a_resend_counts_against_the_new_address_hour(client, signup_env):
    """One request and four resends use up the five an hour; the next resend
    gets no code and the same answer as one that went out."""
    email = signup_env.new_email()
    token = _session(signup_env, email)
    sent_answer = None
    for _ in range(4):
        r = _resend(client, token)
        assert r.status_code == 200
        sent_answer = (r.status_code, r.get_data())
    assert len(signup_env.sent) == 5

    r = _resend(client, token)
    assert (r.status_code, r.get_data()) == sent_answer, 'a refusal looks like a send'
    assert len(signup_env.sent) == 5, 'nothing mailed'
    assert signup_env.refusals() == ['ip_hour']


def test_resends_also_hold_a_request_back(client, signup_env):
    """The counters are shared with /request-otp: resends spend the same
    allowance a fresh request would."""
    email = signup_env.new_email()
    token = _session(signup_env, email)
    for _ in range(4):
        assert _resend(client, token).status_code == 200
    r = signup_env.request(signup_env.new_email(), ip=CLIENT)
    assert not signup_env.issued(r.get_json()['session_token'])
    assert signup_env.refusals() == ['ip_hour']


def test_a_resend_from_a_network_over_its_day_gets_no_code(client, signup_env):
    email = signup_env.new_email()
    token = _session(signup_env, email, ip=f'{NETWORK}10')
    for n in range(19):
        assert _resend(client, token, ip=f'{NETWORK}{n + 11}').status_code == 200
    assert len(signup_env.sent) == 20
    assert _resend(client, token, ip=f'{NETWORK}200').status_code == 200
    assert len(signup_env.sent) == 20
    assert signup_env.refusals() == ['network_day']


def test_a_resend_is_not_refused_for_a_missing_stamp(client, signup_env, monkeypatch):
    email = signup_env.new_email()
    token = _session(signup_env, email)
    monkeypatch.setattr(guard, 'STAMP_REQUIRED', True)
    assert _resend(client, token).status_code == 200
    assert signup_env.sent == [email, email]
    assert signup_env.refusals() == []


def test_a_resend_to_a_domain_that_stopped_taking_mail_gets_no_code(client, signup_env):
    email = signup_env.new_email()
    token = _session(signup_env, email)
    # The day's cached answer runs out and DNS now says no mail.
    signup_env.redis.delete('signupguard:mx:gmail.com')
    signup_env.dns['gmail.com'] = False
    assert _resend(client, token).status_code == 200
    assert signup_env.sent == [email]
    assert signup_env.refusals() == ['no_mx']
