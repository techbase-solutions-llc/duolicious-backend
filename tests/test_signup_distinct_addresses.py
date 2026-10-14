"""One network may ask for codes for at most 5 different new addresses a day.

TEC-1848, item 2 of docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
This is the pattern behind 61 of the 151 unentered codes: one source
cycling through many addresses. The sixth different address with no
account from one network (IPv4 /24, IPv6 /64) in a UTC day is answered as
a send is and gets no code. One of the first five may still ask again.

Each request here comes from its own client address inside the network,
so the per-address limits of item 1 never come into it.
"""

NETWORK = '81.2.69.'


def _code_issued(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    return env.issued(r.get_json()['session_token'])


def _refused_quietly(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    return isinstance(token, str) and len(token) == 128 and not env.issued(token)


def _five(env, network=NETWORK):
    emails = [env.new_email() for _ in range(5)]
    for n, email in enumerate(emails):
        assert _code_issued(env, env.request(email, ip=f'{network}{n + 1}'))
    return emails


def test_the_sixth_different_new_address_from_one_network_gets_no_code(signup_env):
    _five(signup_env)
    r = signup_env.request(signup_env.new_email(), ip=f'{NETWORK}50')
    assert _refused_quietly(signup_env, r)
    assert len(signup_env.sent) == 5
    assert signup_env.refusals() == ['network_addresses']


def test_one_of_the_first_five_may_ask_again(signup_env):
    emails = _five(signup_env)
    assert _refused_quietly(signup_env, signup_env.request(signup_env.new_email(), ip=f'{NETWORK}50'))
    assert _code_issued(signup_env, signup_env.request(emails[0], ip=f'{NETWORK}60'))


def test_a_refused_address_does_not_take_a_place(signup_env):
    """The refused sixth is not held against the network: asking for it again
    is still a sixth address, and refused again, never quietly let in."""
    _five(signup_env)
    sixth = signup_env.new_email()
    assert _refused_quietly(signup_env, signup_env.request(sixth, ip=f'{NETWORK}50'))
    assert _refused_quietly(signup_env, signup_env.request(sixth, ip=f'{NETWORK}51'))


def test_the_next_day_the_network_may_ask_for_new_addresses_again(signup_env):
    _five(signup_env)
    signup_env.advance(86400)
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email(), ip=f'{NETWORK}50'))


def test_another_network_is_counted_apart(signup_env):
    _five(signup_env)
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email(), ip='81.2.70.1'))


def test_ipv6_addresses_in_one_64_share_the_five(signup_env):
    for n in range(5):
        r = signup_env.request(signup_env.new_email(), ip=f'2a01:4f8:c0c:1234::{n + 1}')
        assert _code_issued(signup_env, r)
    r = signup_env.request(signup_env.new_email(), ip='2a01:4f8:c0c:1234:abcd::1')
    assert _refused_quietly(signup_env, r)


def test_no_address_is_kept_in_redis(signup_env):
    emails = _five(signup_env)
    stored = ' '.join(
        ' '.join(signup_env.redis.smembers(key))
        for key in signup_env.redis.scan_iter('signupguard:addresses:*'))
    assert stored
    for email in emails:
        assert email not in stored
        assert email.split('@')[0] not in stored
