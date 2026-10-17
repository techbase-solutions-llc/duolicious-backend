"""Sending a Together invite by email (TEC-1845).

Spec: "Rate limits follow the checklist's (5 an hour per recipient for
invite emails)." Plus the free bot protection every mail-sending endpoint
uses (service.leads.mail_refusal, signupguard): a refused address is
answered exactly as a sent one, and nothing is mailed.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service import leads, signupguard
from service.tools import mail

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


@pytest.fixture
def outbox(monkeypatch):
    """What would be mailed, what signupguard was asked and what it refused."""
    box = dict(sent=[], asked=[], refused=[], answer=None)
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    monkeypatch.setattr(mail, 'send_invite_later', lambda msg: box['sent'].append(msg))

    def refusal(**kw):
        box['asked'].append(kw)
        return box['answer']
    monkeypatch.setattr(leads, 'mail_refusal', refusal)
    monkeypatch.setattr(signupguard, 'record_refusal',
                        lambda reason, **kw: box['refused'].append(reason))
    return box


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _saved(client, headers, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    invite = client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Daniel'),
                         headers=_h(token, headers)).get_json()['invite_token']
    return sid, token, invite


def _send(client, sid, token, headers, to='rivka@ahavah-test.invalid', **extra):
    return client.post(f'/tools/sessions/{sid}/invite-email', json=dict(email=to, **extra),
                       headers=_h(token, headers))


def _count(sid):
    with api_tx() as tx:
        return tx.execute('SELECT invite_emails FROM tool_session WHERE uuid = %(u)s',
                          dict(u=sid)).fetchone()['invite_emails']


def test_the_invite_email_is_off_until_its_switch(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', raising=False)
    _, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers)
    assert (r.status_code, r.get_json()) == (404, {'error': 'off'})


def test_only_the_player_who_saved_can_send_it(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    body = client.post('/tools/sessions', json=dict(kind='game', mode='us')).get_json()
    _MADE.append(body['session_id'])
    r = _send(client, body['session_id'], body['player_token'], headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'not_saved'})
    sid, _, invite = _saved(client, headers)
    guest = client.post(f'/tools/i/{invite}/players', json=dict(display='Rivka')).get_json()['player_token']
    _, guest_headers = tool_visitor()
    assert _send(client, sid, guest, guest_headers).status_code == 403
    sid_me, token_me, _ = _saved(client, headers, mode='me')
    assert _send(client, sid_me, token_me, headers).get_json() == {'error': 'bad_mode'}
    assert outbox['sent'] == []


def test_one_invite_goes_with_the_players_name_and_link(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    sid, token, invite = _saved(client, headers)
    r = _send(client, sid, token, headers, signup_stamp='stamp-1')
    assert (r.status_code, r.get_json()) == (202, {'sent': True})
    [msg] = outbox['sent']
    assert msg['to'] == 'rivka@ahavah-test.invalid'
    assert msg['subject'] == 'Daniel wants to see how well you fit'
    assert f'/tools/i/{invite}' in msg['html'] and 'You both see the score.' in msg['html']
    assert _count(sid) == 1
    assert outbox['asked'][0]['stamp'] == 'stamp-1' and outbox['asked'][0]['email'] == 'rivka@ahavah-test.invalid'


def test_a_refused_address_is_answered_as_a_send_and_nothing_goes(client, tool_visitor, outbox):
    outbox['answer'] = 'bad_domain'
    _, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers)
    assert (r.status_code, r.get_json()) == (202, {'sent': True})
    assert outbox['sent'] == [] and outbox['refused'] == ['bad_domain'] and _count(sid) == 0


def test_a_player_cannot_invite_their_own_address(client, tool_visitor, outbox):
    email, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers, to=email)
    assert (r.status_code, r.get_json()) == (400, {'error': 'own_address'})


def test_the_checklist_invite_names_the_checklist(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    sid, token, invite = _saved(client, headers, mode='couple', kind='checklist')
    _send(client, sid, token, headers)
    [msg] = outbox['sent']
    assert msg['subject'] == 'Daniel invited you to the Ahavah marriage checklist'
    assert 'Your answers stay private until you have both finished.' in msg['html']
    assert f'/tools/i/{invite}' in msg['html']
