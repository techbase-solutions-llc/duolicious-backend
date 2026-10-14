"""Tighter code limits for addresses with no account.

TEC-1848, item 1 of docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
A request for an address that has no account counts against 5 an hour and
10 a day per client address, and 20 a day per network (IPv4 /24, IPv6 /64).
Requests for existing accounts keep today's limits, so members signing in,
admins included, are unaffected. A request over a limit is answered as a
send is (200 and a session token) and nothing is mailed.
"""
from database import api_tx
import service.signupguard as guard

# Public addresses: private ones are exempt, as from the shared OTP limits.
CLIENT = '45.33.10.7'
NEIGHBOUR_NETWORK = '45.33.10.'
OTHER_NETWORK = '45.33.11.5'


def _code_issued(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    return env.issued(r.get_json()['session_token'])


def _refused_quietly(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    return isinstance(token, str) and len(token) == 128 and not env.issued(token)


def _member(make_person, admin=False) -> str:
    p = make_person(name='LimitMember')
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                       dict(i=p['id']))
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=p['id'])).fetchone()['email']


def _spend_the_hour(env, ip=CLIENT):
    """Five code requests for one new address: the hourly limit, used up.
    One address, so the rule on distinct addresses does not come into it."""
    email = env.new_email()
    for _ in range(5):
        assert _code_issued(env, env.request(email, ip=ip))
    return email


def test_a_sixth_request_in_an_hour_for_a_new_address_gets_no_code(signup_env):
    email = _spend_the_hour(signup_env)
    r = signup_env.request(email, ip=CLIENT)
    assert _refused_quietly(signup_env, r)
    assert len(signup_env.sent) == 5
    assert signup_env.refusals() == ['ip_hour']


def test_the_hourly_limit_lifts_the_next_hour(signup_env):
    email = _spend_the_hour(signup_env)
    signup_env.advance(3600)
    assert _code_issued(signup_env, signup_env.request(email, ip=CLIENT))


def test_an_eleventh_request_in_a_day_for_a_new_address_gets_no_code(signup_env):
    email = _spend_the_hour(signup_env)
    signup_env.advance(3600)
    for _ in range(5):
        assert _code_issued(signup_env, signup_env.request(email, ip=CLIENT))
    signup_env.advance(3600)
    assert _refused_quietly(signup_env, signup_env.request(email, ip=CLIENT))
    assert signup_env.refusals() == ['ip_day']
    signup_env.advance(86400)
    assert _code_issued(signup_env, signup_env.request(email, ip=CLIENT))


def test_a_network_gets_twenty_new_address_requests_a_day(signup_env):
    email = signup_env.new_email()
    for n in range(20):
        r = signup_env.request(email, ip=f'{NEIGHBOUR_NETWORK}{n + 10}')
        assert _code_issued(signup_env, r), n
    r = signup_env.request(email, ip=f'{NEIGHBOUR_NETWORK}200')
    assert _refused_quietly(signup_env, r)
    assert signup_env.refusals() == ['network_day']
    # Another network is counted on its own.
    assert _code_issued(signup_env, signup_env.request(email, ip=OTHER_NETWORK))


def test_networks_are_the_ipv4_24_and_the_ipv6_64():
    assert guard.network_of('45.33.10.7') == '45.33.10.0/24'
    assert guard.network_of('::ffff:45.33.10.7') == '45.33.10.0/24'
    assert guard.network_of('2a01:4f8:c0c:1234::1') == '2a01:4f8:c0c:1234::/64'
    assert (guard.network_of('2a01:4f8:c0c:1234:ffff:1:2:3')
            == guard.network_of('2a01:4f8:c0c:1234::9'))
    assert guard.network_of('not an address') is None


def test_a_member_still_gets_a_code_where_the_new_address_limit_is_spent(
        signup_env, make_person):
    email = _spend_the_hour(signup_env)
    assert _refused_quietly(signup_env, signup_env.request(email, ip=CLIENT))
    member = _member(make_person)
    r = signup_env.request(member, ip=CLIENT)
    assert _code_issued(signup_env, r)
    assert signup_env.sent[-1] == member


def test_an_admin_still_gets_a_code_where_the_new_address_limit_is_spent(
        signup_env, make_person):
    email = _spend_the_hour(signup_env)
    assert _refused_quietly(signup_env, signup_env.request(email, ip=CLIENT))
    admin = _member(make_person, admin=True)
    assert _code_issued(signup_env, signup_env.request(admin, ip=CLIENT))
    assert signup_env.sent[-1] == admin


def test_members_signing_in_never_use_up_the_new_address_limit(signup_env, make_person):
    member = _member(make_person)
    for _ in range(8):
        assert _code_issued(signup_env, signup_env.request(member, ip=CLIENT))
    # The hour's five new-address requests are all still there.
    _spend_the_hour(signup_env)
    assert signup_env.refusals() == []


def test_a_private_address_is_exempt_as_from_the_shared_limits(signup_env):
    email = signup_env.new_email()
    for _ in range(7):
        assert _code_issued(signup_env, signup_env.request(email, ip='10.184.8.1'))


def test_the_limits_fail_open_when_redis_is_unreachable(signup_env, monkeypatch):
    import redis

    class _Down:
        def pipeline(self, *a, **k):
            raise redis.exceptions.ConnectionError('down')

        def __getattr__(self, name):
            raise redis.exceptions.ConnectionError('down')

    monkeypatch.setattr(guard, '_redis', lambda: _Down())
    email = signup_env.new_email()
    for _ in range(7):
        assert _code_issued(signup_env, signup_env.request(email, ip=CLIENT))
