"""A sign-up from a gathering's join link is credited to the gathering
(TEC-1845, docs/superpowers/plans/2026-10-22-events-invite-to-join.md,
Task 4). The web keeps `src=event:{slug}` for 30 days on the device and
sends it to /check-otp as `source`; the API stamps it on a NEW onboardee
when the gathering exists, and finish-onboarding copies it to the person.
It beats the first touch (Owner decision 5). A value the web did not
expect is ignored, never a 400 that blocks sign-in, and the join link
writes no lead."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema')


@pytest.fixture
def lead_emails():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=[m.lower() for m in made]))


def _new_address(lead_emails) -> str:
    # A new example.com address is given 000000 in the dev environment.
    email = f'join-{uuid4().hex[:12]}@example.com'
    lead_emails.append(email)
    return email


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


def _finish(finish_onboarding, email: str, first_touch: dict | None = None):
    """Finish sign-up as the web does after /check-otp: the onboardee the
    code created, with its tag, becomes the person. The fixture builds a
    complete onboardee, so the code's row is replaced by one carrying the
    same tag."""
    tag = _onboardee_tag(email)
    with api_tx() as tx:
        tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))
    body = dict(first_touch=first_touch) if first_touch else None
    r, pid = finish_onboarding(body, lead_source=tag, email=email)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        return tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                          dict(i=pid)).fetchone()['lead_source']


def _leads_of(email: str) -> list[str]:
    with api_tx('read committed') as tx:
        return [r['source'] for r in tx.execute(
            'SELECT source FROM lead WHERE email = %(e)s ORDER BY id',
            dict(e=email.lower())).fetchall()]


def test_a_new_member_from_the_join_link_is_credited_to_the_gathering(
        client, signup_env, finish_onboarding, published, lead_emails):
    slug = published()
    email = _new_address(lead_emails)
    r = _check(client, signup_env, email, f'event:{slug}')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _onboardee_tag(email) == f'event:{slug}'
    assert _finish(finish_onboarding, email) == f'event:{slug}'


def test_a_different_address_from_the_rsvp_is_still_credited(
        client, signup_env, finish_onboarding, published, confirmed_guest, lead_emails):
    slug = published()
    confirmed_guest(slug, email=f'rsvp-{uuid4().hex[:10]}@ahavah-test.invalid')
    email = _new_address(lead_emails)
    assert _check(client, signup_env, email, f'event:{slug}').status_code == 200
    assert _finish(finish_onboarding, email) == f'event:{slug}'


def test_the_join_link_beats_the_first_touch(
        client, signup_env, finish_onboarding, published, lead_emails):
    slug = published()
    email = _new_address(lead_emails)
    assert _check(client, signup_env, email, f'event:{slug}').status_code == 200
    assert _finish(finish_onboarding, email, {'utm_source': 'facebook'}) == f'event:{slug}'


def test_an_existing_member_is_not_retagged(client, signup_env, make_person, published):
    slug = published()
    person = make_person(name='JoinMember')
    with api_tx() as tx:
        tx.execute("UPDATE person SET lead_source = 'utm:instagram' WHERE id = %(i)s",
                   dict(i=person['id']))
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=person['id'])).fetchone()['email']
    r = _check(client, signup_env, email, f'event:{slug}')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['onboarded'] is True
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                          dict(i=person['id'])).fetchone()['lead_source'] == 'utm:instagram'
    assert _onboardee_tag(email) is None


@pytest.mark.parametrize('value', [
    'event:no-such-gathering-x9', 'event:<script>', 'event:', 'event:' + 'a' * 55,
    'tool:roulette', 12345,
])
def test_an_unknown_or_malformed_event_source_is_ignored(
        client, signup_env, finish_onboarding, lead_emails, value):
    if isinstance(value, str) and value.startswith('event:a'):
        assert len(value) == 61
    email = _new_address(lead_emails)
    r = _check(client, signup_env, email, value)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _onboardee_tag(email) is None
    assert _finish(finish_onboarding, email, {'utm_source': 'facebook'}) == 'utm:facebook'


def test_the_join_link_writes_no_lead(client, signup_env, published, lead_emails, monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    slug = published()
    email = _new_address(lead_emails)
    assert _check(client, signup_env, email, f'event:{slug}').status_code == 200
    assert _leads_of(email) == []


@pytest.mark.parametrize('sent, stored', [
    ('marriage_checklist', 'tool:checklist'),
    ('tool:game-me', 'tool:game-me'),
])
def test_the_tool_sources_still_work(client, signup_env, lead_emails, monkeypatch, sent, stored):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    email = _new_address(lead_emails)
    assert _check(client, signup_env, email, sent).status_code == 200
    assert _onboardee_tag(email) == stored
    assert _leads_of(email) == [stored]


def test_signup_source_reads_each_kind():
    from service.leads.sources import signup_source
    assert signup_source('marriage_checklist') == 'tool:checklist'
    assert signup_source('tool:knows-me') == 'tool:knows-me'
    assert signup_source('event:marriage-evening-a1b2c3') == 'event:marriage-evening-a1b2c3'
    for bad in ('event:', 'event:Bad_Slug', 'event:<b>', 'utm:facebook', 'alert:visitor', None, 7):
        assert signup_source(bad) is None, bad
