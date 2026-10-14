"""No code for a new address on a domain that cannot take mail.

TEC-1848, item 5 of docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
A new address whose domain has no MX record (and no A or AAAA record to
fall back on, or a null MX), or is on the repo's bad-domain list
(email-domains-bad.sql, loaded into bad_email_domain), gets no code. The
answer is the same as for any send, so it reveals nothing.

DNS answers are cached in Redis for a day. A lookup that times out or
fails lets the code through: a resolver hiccup must never stop a sign-up.
Existing accounts are never looked up, and a domain on neither list is
refused with a 400 exactly as before.
"""
from types import SimpleNamespace

import dns.exception
import dns.resolver
import pytest

from database import api_tx
import service.signupguard as guard


def _code_issued(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    return env.issued(r.get_json()['session_token'])


def _refused_quietly(env, r) -> bool:
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    return isinstance(token, str) and len(token) == 128 and not env.issued(token)


def test_a_new_address_on_a_domain_that_cannot_take_mail_gets_no_code(signup_env):
    signup_env.dns['gmail.com'] = False
    assert _refused_quietly(signup_env, signup_env.request(signup_env.new_email()))
    assert signup_env.sent == []
    assert signup_env.refusals() == ['no_mx']


def test_a_new_address_on_the_bad_domain_list_gets_no_code_and_no_error(signup_env):
    """mailinator.com is in email-domains-bad.sql. Before this, the caller
    was told 400 'Disposable email'."""
    r = signup_env.request(signup_env.new_email('mailinator.com'))
    assert _refused_quietly(signup_env, r)
    assert signup_env.sent == []
    assert signup_env.refusals() == ['bad_domain']
    assert signup_env.dns_calls == []


def test_a_domain_on_neither_list_is_still_refused_as_before(signup_env):
    r = signup_env.request(signup_env.new_email('sg-not-a-listed-domain.test'))
    assert r.status_code == 400
    assert signup_env.refusals() == []


def test_the_answer_is_cached_for_a_day(signup_env):
    for _ in range(3):
        assert _code_issued(signup_env, signup_env.request(signup_env.new_email()))
    assert signup_env.dns_calls == ['gmail.com']
    ttl = signup_env.redis.ttl('signupguard:mx:gmail.com')
    assert 86400 - 60 <= ttl <= 86400


def test_a_domain_that_cannot_take_mail_is_remembered_too(signup_env):
    signup_env.dns['gmail.com'] = False
    signup_env.request(signup_env.new_email())
    signup_env.request(signup_env.new_email())
    assert signup_env.dns_calls == ['gmail.com']
    assert signup_env.refusals() == ['no_mx', 'no_mx']


def test_a_dns_failure_lets_the_code_through_and_is_not_remembered(signup_env):
    signup_env.dns['gmail.com'] = None
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email()))
    assert signup_env.redis.get('signupguard:mx:gmail.com') is None
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email()))
    assert signup_env.dns_calls == ['gmail.com', 'gmail.com']


def test_example_com_is_never_looked_up(signup_env):
    """No mail is ever sent to example.com (service/person._send_otp), and
    in real DNS it has a null MX, so the local and test flows that sign up
    with it would otherwise stop getting their 000000 code."""
    assert _code_issued(signup_env, signup_env.request(signup_env.new_email('example.com')))
    assert signup_env.dns_calls == []


def test_a_member_is_never_looked_up(signup_env, make_person):
    p = make_person(name='DomainMember')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['email']
    signup_env.dns['example.com'] = False
    assert _code_issued(signup_env, signup_env.request(email))
    assert signup_env.dns_calls == []


# The lookup itself, against a stand-in resolver.

class _Resolver:
    def __init__(self, answers):
        self.answers = answers
        self.lifetime = None

    def resolve(self, domain, rdtype):
        outcome = self.answers.get(rdtype, dns.resolver.NoAnswer)
        if isinstance(outcome, type) and issubclass(outcome, Exception):
            raise outcome()
        return [SimpleNamespace(exchange=x) for x in outcome] if rdtype == 'MX' else outcome


@pytest.mark.parametrize('answers, expected', [
    ({'MX': ['alt1.gmail-smtp-in.l.google.com.']}, True),
    ({'MX': ['.']}, False),                                   # null MX, RFC 7505
    ({'MX': dns.resolver.NXDOMAIN}, False),
    ({'MX': dns.resolver.NoAnswer, 'A': ['192.0.2.1']}, True),  # falls back to A
    ({'MX': dns.resolver.NoAnswer, 'AAAA': ['2001:db8::1']}, True),
    ({'MX': dns.resolver.NoAnswer}, False),                   # no record at all
    ({'MX': dns.exception.Timeout}, None),
    ({'MX': dns.resolver.NoNameservers}, None),
    ({'MX': dns.resolver.NoAnswer, 'A': dns.exception.Timeout}, None),
])
def test_what_a_dns_answer_means(monkeypatch, answers, expected):
    monkeypatch.setattr(dns.resolver, 'Resolver', lambda *a, **k: _Resolver(answers))
    assert guard._resolve_mail_domain('somewhere.example') is expected
