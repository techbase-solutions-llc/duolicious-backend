"""Saving a Together result (TEC-1845).

Spec: "Saving a result, comparing with someone and getting the share image
needs an email confirmed by a 6-digit code. This is the same one-time code
and onboardee session the checklist already uses." The claim reads the
address from that session, never from the request. A lead is written only
while AHAVAH_TOOL_LEADS_ENABLED is on; a member is never a lead.
"""
from __future__ import annotations

import secrets

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _start(client, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    _MADE.append(body['session_id'])
    return body['session_id'], body['player_token']


def _claim(client, sid, token, headers, display='Daniel'):
    return client.post(f'/tools/sessions/{sid}/claim', json=dict(display=display),
                       headers=_h(token, headers))


def test_saving_needs_a_signed_in_session(client):
    sid, token = _start(client)
    assert client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Daniel'),
                       headers=_h(token)).status_code == 400


def test_a_visitor_saves_with_their_confirmed_email(client, tool_visitor):
    email, headers = tool_visitor()
    sid, token = _start(client)
    v = _claim(client, sid, token, headers).get_json()
    assert v['claimed'] is True and len(v['share_token']) == 22 and len(v['invite_token']) == 22
    with api_tx() as tx:
        s = tx.execute("""SELECT owner_email, owner_display, claimed_at IS NOT NULL AS saved
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
    assert dict(s) == dict(owner_email=email, owner_display='Daniel', saved=True)


def test_me_gets_a_share_link_and_no_invite(client, tool_visitor):
    _, headers = tool_visitor()
    sid, token = _start(client, mode='me')
    v = _claim(client, sid, token, headers).get_json()
    assert v['share_token'] and v['invite_token'] is None


def test_saving_twice_is_the_same_save_and_another_address_is_refused(client, tool_visitor):
    _, headers = tool_visitor()
    _, other = tool_visitor()
    sid, token = _start(client)
    first = _claim(client, sid, token, headers).get_json()
    again = _claim(client, sid, token, headers, display='D.').get_json()
    assert (again['share_token'], again['invite_token'], again['my_display']) == (
        first['share_token'], first['invite_token'], 'D.')
    r = _claim(client, sid, token, other)
    assert (r.status_code, r.get_json()) == (409, {'error': 'claimed'})


def test_an_us_guest_saves_their_own_email_and_gets_the_share_link(client, tool_visitor):
    _, owner_headers = tool_visitor()
    _, guest_headers = tool_visitor()
    sid, owner = _start(client)
    invite = _claim(client, sid, owner, owner_headers).get_json()['invite_token']
    guest = client.post(f'/tools/i/{invite}/players', json=dict(display='Rivka')).get_json()['player_token']
    before = client.get(f'/tools/sessions/{sid}', headers=_h(guest)).get_json()
    assert (before['claimed'], before['share_token']) == (False, None)
    after = _claim(client, sid, guest, guest_headers, display='R.').get_json()
    assert after['claimed'] is True and after['share_token'] and after['my_display'] == 'R.'
    assert after['invite_token'] is None


def test_a_knows_me_friend_cannot_save(client, tool_visitor):
    _, owner_headers = tool_visitor()
    _, friend_headers = tool_visitor()
    sid, owner = _start(client, mode='knows_me')
    client.post(f'/tools/sessions/{sid}/finish', headers=_h(owner))
    invite = _claim(client, sid, owner, owner_headers).get_json()['invite_token']
    friend = client.post(f'/tools/i/{invite}/players', json=dict(display='Hannah')).get_json()['player_token']
    r = _claim(client, sid, friend, friend_headers)
    assert (r.status_code, r.get_json()) == (403, {'error': 'not_allowed'})


def _leads(email):
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            'SELECT source, confirmed_via FROM lead WHERE email = %(e)s', dict(e=email)).fetchall()]


def test_a_lead_is_written_only_while_tool_leads_are_on(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    email, headers = tool_visitor()
    sid, token = _start(client)
    _claim(client, sid, token, headers)
    assert _leads(email) == []
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    email2, headers2 = tool_visitor()
    sid2, token2 = _start(client, mode='couple', kind='checklist')
    _claim(client, sid2, token2, headers2)
    assert _leads(email2) == [dict(source='tool:checklist', confirmed_via='otp')]


def test_a_member_saves_to_their_account_and_is_never_a_lead(client, make_person, sign_in,
                                                             monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    member = make_person(name='Samuel', email=f'm-{secrets.token_hex(6)}@ahavah-test.invalid')
    sid, token = _start(client)
    v = _claim(client, sid, token, sign_in(member), display='Samuel').get_json()
    assert v['claimed'] is True and v['member'] is True
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=member['id'])).fetchone()['email']
    assert owner == member['id'] and _leads(email) == []


def test_finishing_sign_up_links_earlier_sessions(client, tool_visitor, finish_onboarding):
    email, headers = tool_visitor(f'join-{secrets.token_hex(6)}@ahavah-test.invalid')
    sid, token = _start(client)
    _claim(client, sid, token, headers)
    r, person_id = finish_onboarding({}, email=email)
    assert r.status_code == 200 and person_id
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
    assert owner == person_id
