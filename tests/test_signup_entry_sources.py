"""Sign-up sources for the entries that recorded none (TEC-1929, ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 8).

Fix 8: the visitor alert email's "Join to see them" opens sign-up with
from=alert. The web keeps it as the source alert:visitor and sends it to
/check-otp, which stamps it on a NEW onboardee, so the sign-up is credited
to the alert even from another address. Like a gathering's join link it
writes no lead: the visitor's own alert lead already exists.

Fix 10: a mentor, a host and a /families visitor sender gave an address
without coming to marry. They are never leads; when one of them later
joins, finish-onboarding sets person.lead_source to 'mentor', 'host' or
'family' only if nothing else named a source. Attribution only: no lead,
so nothing makes them eligible for news."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema')


@pytest.fixture
def addresses():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        es = [m.lower() for m in made]
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=es))
        tx.execute('DELETE FROM mentor_account WHERE email = ANY(%(e)s)', dict(e=es))
        tx.execute('DELETE FROM organiser WHERE email = ANY(%(e)s)', dict(e=es))
        tx.execute("DELETE FROM recommendation WHERE sender_first_name = 'EntrySourceTest'")


def _new_address(addresses, kind: str = 'entry') -> str:
    # A new example.com address is given 000000 in the dev environment.
    email = f'{kind}-{uuid4().hex[:12]}@example.com'
    addresses.append(email)
    return email


def _normalised(email: str) -> str:
    from service.leads import clean_email
    return clean_email(email)[1]


def _check(client, signup_env, email: str, source):
    token = signup_env.request(email).get_json()['session_token']
    body = dict(otp='000000')
    if source is not None:
        body['source'] = source
    return client.post('/check-otp', json=body, headers={'Authorization': f'Bearer {token}'})


def _onboardee_tag(email: str):
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                         dict(e=email)).fetchone()
    return row['lead_source'] if row else None


def _finish(finish_onboarding, email: str, *, tag=None, first_touch: dict | None = None):
    body = dict(first_touch=first_touch) if first_touch else None
    r, pid = finish_onboarding(body, lead_source=tag, email=email)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        return tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                          dict(i=pid)).fetchone()['lead_source']


def _finish_after_code(finish_onboarding, email: str):
    """As the web does after /check-otp: the onboardee the code created, with
    its tag, becomes the person (the fixture builds a complete one)."""
    tag = _onboardee_tag(email)
    with api_tx() as tx:
        tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))
    return _finish(finish_onboarding, email, tag=tag)


def _leads_of(email: str) -> list[str]:
    with api_tx('read committed') as tx:
        return [r['source'] for r in tx.execute(
            'SELECT source FROM lead WHERE email = %(e)s ORDER BY id',
            dict(e=email.lower())).fetchall()]


def _mentor(email: str) -> None:
    with api_tx() as tx:
        tx.execute('INSERT INTO mentor_account (email, normalized_email) VALUES (%(e)s, %(ne)s)',
                   dict(e=email, ne=_normalised(email)))


def _host(email: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO organiser (name, kind, email, normalized_email, verified_at)
               VALUES ('Entry Source Host', 'fellowship_leader', %(e)s, %(ne)s, NOW())""",
            dict(e=email, ne=_normalised(email)))


def _family_sender(email: str) -> None:
    from service.matchmaker import address_key
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO recommendation (sender_person_id, sender_key, sender_first_name,
                                           recipient_key, status, sent_at)
               VALUES (NULL, %(sk)s, 'EntrySourceTest', %(rk)s, 'sent', NOW())""",
            dict(sk=address_key(_normalised(email)), rk='test-' + uuid4().hex))


# --- Fix 8: from=alert ------------------------------------------------------

def test_a_sign_up_from_the_alert_email_is_credited_to_the_alert(
        client, signup_env, finish_onboarding, addresses):
    email = _new_address(addresses, 'alertjoin')
    r = _check(client, signup_env, email, 'alert:visitor')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _onboardee_tag(email) == 'alert:visitor'
    assert _finish_after_code(finish_onboarding, email) == 'alert:visitor'


def test_the_alert_source_writes_no_lead(client, signup_env, addresses, monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    email = _new_address(addresses, 'alertjoin')
    assert _check(client, signup_env, email, 'alert:visitor').status_code == 200
    assert _leads_of(email) == []


@pytest.mark.parametrize('value', ['alert:other', 'alert', 'mentor', 'host', 'family', 'intro'])
def test_other_alert_like_or_role_values_are_ignored_at_check_otp(
        client, signup_env, addresses, value):
    email = _new_address(addresses, 'alertjoin')
    assert _check(client, signup_env, email, value).status_code == 200
    assert _onboardee_tag(email) is None


# --- Fix 10: mentor, host, family -------------------------------------------

@pytest.mark.parametrize('make, source', [
    (_mentor, 'mentor'), (_host, 'host'), (_family_sender, 'family'),
])
def test_a_mentor_host_or_family_sender_who_joins_is_credited(
        finish_onboarding, addresses, make, source):
    email = _new_address(addresses, source)
    make(email)
    assert _finish(finish_onboarding, email) == source


@pytest.mark.parametrize('make', [_mentor, _host, _family_sender])
def test_an_earlier_source_is_kept(finish_onboarding, addresses, make):
    email = _new_address(addresses, 'kept')
    make(email)
    assert _finish(finish_onboarding, email, tag='tool:game-us') == 'tool:game-us'
    email = _new_address(addresses, 'kept')
    make(email)
    assert _finish(finish_onboarding, email, first_touch={'utm_source': 'facebook'}) == 'utm:facebook'


def test_mentor_comes_before_host_before_family(finish_onboarding, addresses):
    email = _new_address(addresses, 'all')
    _family_sender(email)
    _host(email)
    assert _finish(finish_onboarding, email) == 'host'
    email = _new_address(addresses, 'all')
    _family_sender(email)
    _host(email)
    _mentor(email)
    assert _finish(finish_onboarding, email) == 'mentor'


def test_nobody_else_is_given_a_role_source(finish_onboarding, addresses):
    email = _new_address(addresses, 'plain')
    _mentor(_new_address(addresses, 'other'))
    assert _finish(finish_onboarding, email) is None


@pytest.mark.parametrize('make', [_mentor, _host, _family_sender])
def test_a_role_source_writes_no_lead(finish_onboarding, addresses, monkeypatch, make):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    email = _new_address(addresses, 'nolead')
    make(email)
    _finish(finish_onboarding, email)
    assert _leads_of(email) == []


def test_role_sources_are_never_lead_sources():
    from service.leads.sources import FAMILY, HOST, MENTOR, is_lead_source, signup_source
    for value in (MENTOR, HOST, FAMILY):
        assert not is_lead_source(value)
        assert signup_source(value) is None


def test_a_failing_role_lookup_never_fails_the_sign_up(finish_onboarding, addresses, monkeypatch):
    import service.person.attribution as attribution
    monkeypatch.setattr(attribution, '_ROLE_SOURCE_SQL', 'SELECT no_such_column FROM person')
    email = _new_address(addresses, 'boom')
    _mentor(email)
    assert _finish(finish_onboarding, email) is None
