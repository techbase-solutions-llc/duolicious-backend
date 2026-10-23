"""Leads at sign-in and sign-up (TEC-1845).

A couple tool confirms the player's address with the sign-in code the
marriage checklist already uses (/request-otp, /check-otp). That code is
the proof, so /check-otp records the tool's lead as confirmed. When the
player later finishes sign-up, their confirmed leads are linked to the new
member and name where they came from, ahead of the device's first touch;
the onboardee's own tag still comes first.

Recording a tool's lead at /check-otp is behind AHAVAH_TOOL_LEADS_ENABLED,
off until the privacy page describes it. These tests turn it on, except the
one that pins the off state.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx
from service.leads import confirm_lead, record_lead

pytestmark = pytest.mark.usefixtures('growth_schema')


@pytest.fixture(autouse=True)
def _tool_leads_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')


@pytest.fixture
def lead_emails():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=[m.lower() for m in made]))


def _leads_of(email: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT source, confirmed_at, confirmed_via, person_id, converted_at
                 FROM lead WHERE email = %(e)s ORDER BY id""",
            dict(e=email.lower())).fetchall()]


def _check(client, token: str, source):
    body = dict(otp='000000')
    if source is not None:
        body['source'] = source
    return client.post('/check-otp', json=body, headers={'Authorization': f'Bearer {token}'})


def _new_address(lead_emails) -> str:
    # A new example.com address is given 000000 in the dev environment the
    # tests run in, and is never mailed or looked up.
    email = f'tool-{uuid4().hex[:12]}@example.com'
    lead_emails.append(email)
    return email


def test_a_tool_player_confirming_by_code_becomes_a_confirmed_lead(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    r = _check(client, token, 'tool:game-us')
    assert r.status_code == 200, r.get_data(as_text=True)
    leads = _leads_of(email)
    assert [(x['source'], x['confirmed_via']) for x in leads] == [('tool:game-us', 'otp')]
    assert leads[0]['confirmed_at'] is not None and leads[0]['person_id'] is None
    with api_tx('read committed') as tx:
        tag = tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                         dict(e=email)).fetchone()['lead_source']
    assert tag == 'tool:game-us'


def test_the_checklist_old_name_is_stored_as_tool_checklist(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'marriage_checklist').status_code == 200
    assert [x['source'] for x in _leads_of(email)] == ['tool:checklist']
    with api_tx('read committed') as tx:
        tag = tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                         dict(e=email)).fetchone()['lead_source']
    assert tag == 'tool:checklist'


def test_a_member_signing_in_from_a_tool_is_not_a_lead(client, signup_env, make_person, lead_emails):
    person = make_person(name='ToolMember')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=person['id'])).fetchone()['email']
    lead_emails.append(email)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'tool:game-me').status_code == 200
    assert _leads_of(email) == []


def test_while_the_switch_is_off_the_live_checklist_records_no_lead(
        client, signup_env, lead_emails, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'marriage_checklist').status_code == 200
    assert _leads_of(email) == []


def test_a_sign_in_with_no_source_records_no_lead(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, None).status_code == 200
    assert _leads_of(email) == []


def test_an_unknown_source_is_ignored(client, signup_env, lead_emails):
    """Was a 400; since the join link (TEC-1845, inviting guests to join)
    a value the web did not expect is ignored, never a refused sign-in."""
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'tool:roulette').status_code == 200
    assert _leads_of(email) == []


def _confirmed_lead(email: str, source: str) -> int:
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source=source)
        confirm_lead(tx, lead_id, 'link')
    return lead_id


def test_finishing_sign_up_links_the_lead_and_takes_its_source(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    _confirmed_lead(email, 'event:sukkot-2027')
    r, pid = finish_onboarding(dict(first_touch={'utm_source': 'instagram'}), email=email)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'event:sukkot-2027'
    [lead] = _leads_of(email)
    assert lead['person_id'] == pid and lead['converted_at'] is not None


def test_an_unconfirmed_lead_neither_links_nor_names_the_source(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    with api_tx() as tx:
        record_lead(tx, email=email, source='alert:visitor')
    r, pid = finish_onboarding(dict(first_touch={'utm_source': 'instagram'}), email=email)
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'utm:instagram'
    assert _leads_of(email)[0]['person_id'] is None


def test_the_onboardees_own_tag_comes_before_a_lead(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    _confirmed_lead(email, 'event:sukkot-2027')
    r, pid = finish_onboarding({}, lead_source='tool:checklist', email=email)
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'tool:checklist'
    assert _leads_of(email)[0]['person_id'] == pid
