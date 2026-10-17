"""Together's emails (TEC-1845).

Owner decision 5: one email through the outbox to the first player when
the second has finished, proofed first. Owner decision 12: the checklist
summary stays, now sent to each player when they finish, with the
stored-answers line, plus "your comparison is ready". Each is behind its
own switch and needs together_live. Nothing here ever breaks a finish.
"""
from __future__ import annotations

import secrets

import pytest

from database import api_tx
from emails.marriage_checklist import STORED_LINE, checklist_results_html
from service.tools import mail

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute("DELETE FROM email_outbox WHERE campaign_id LIKE %(c)s", dict(c=f'{sid}%'))
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


@pytest.fixture
def switches(monkeypatch):
    for env in ('AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED', 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
                'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED'):
        monkeypatch.setenv(env, '1')


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _mailable(make_person, name):
    return make_person(name=name, email=f'{name.lower()}-{secrets.token_hex(5)}@ahavah-test.invalid')


def _start(client, headers, mode='us', kind='game', display='Daniel'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode), headers=headers).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    v = client.post(f'/tools/sessions/{sid}/claim', json=dict(display=display),
                    headers=_h(token, headers)).get_json()
    return sid, token, v['invite_token']


def _play(client, sid, token, answers, role=None):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, role=role),
                headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _join(client, invite, display='Rivka'):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display)).get_json()['player_token']


def _rows(sid):
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign, campaign_id, person_id, lead_id, payload FROM email_outbox
                WHERE campaign_id LIKE %(c)s ORDER BY id""", dict(c=f'{sid}%')).fetchall()]


def test_the_answered_email_goes_to_whoever_finished_first(client, make_person, sign_in, switches):
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    guest = _join(client, invite)
    assert _play(client, sid, guest, {'calendar': 'enoch'}).status_code == 200
    rows = [r for r in _rows(sid) if r['campaign'] == mail.CAMPAIGN_ANSWERED]
    assert len(rows) == 1 and rows[0]['person_id'] == owner['id'] and rows[0]['campaign_id'] == sid
    assert rows[0]['payload']['subject'] == 'Rivka has answered. See how you fit.'
    assert f'/together/game?session={sid}' in rows[0]['payload']['html']


def test_the_answered_footer_says_why_by_seat(client, make_person, sign_in, switches):
    """Review, 17 Oct 2026: the footer always said "you invited", but the
    email goes to whoever finished first, which can be the guest."""
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    [to_owner] = [r for r in _rows(sid) if r['campaign'] == mail.CAMPAIGN_ANSWERED]
    assert 'You get this because you invited Rivka' in to_owner['payload']['html']

    owner2 = _mailable(make_person, 'Daniel')
    guest = _mailable(make_person, 'Rivka')
    sid2, token2, invite2 = _start(client, sign_in(owner2))
    guest_token = client.post(f'/tools/i/{invite2}/players', json=dict(display='Rivka'),
                              headers=sign_in(guest)).get_json()['player_token']
    _play(client, sid2, guest_token, {'calendar': 'enoch'})
    _play(client, sid2, token2, {'calendar': 'enoch'})
    [to_guest] = [r for r in _rows(sid2) if r['campaign'] == mail.CAMPAIGN_ANSWERED]
    assert to_guest['person_id'] == guest['id']
    html = to_guest['payload']['html']
    assert 'You get this because Daniel invited you' in html and 'you invited' not in html


def test_a_visitor_owner_is_mailed_as_a_lead_only_while_tool_leads_are_on(client, tool_visitor,
                                                                         switches, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    _, headers = tool_visitor()
    sid, token, invite = _start(client, headers)
    _play(client, sid, token, {'calendar': 'enoch'})
    _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert _rows(sid) == []
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    _, headers2 = tool_visitor()
    sid2, token2, invite2 = _start(client, headers2)
    _play(client, sid2, token2, {'calendar': 'enoch'})
    _play(client, sid2, _join(client, invite2), {'calendar': 'enoch'})
    rows = _rows(sid2)
    assert len(rows) == 1 and rows[0]['lead_id'] is not None and rows[0]['person_id'] is None


def test_nothing_is_queued_while_its_switch_is_off(client, make_person, sign_in):
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert _rows(sid) == []


def test_the_checklist_uses_the_ready_switch_and_link(client, make_person, sign_in, monkeypatch):
    monkeypatch.setenv('AHAVAH_TOGETHER_READY_EMAIL_ENABLED', '1')
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner), mode='couple', kind='checklist')
    item = dict(section='biblical', importance=4, stance='agree')
    _play(client, sid, token, {'p1': item}, role='husband')
    _play(client, sid, _join(client, invite), {'p1': item}, role='wife')
    rows = _rows(sid)
    assert [r['campaign'] for r in rows] == [mail.CAMPAIGN_READY]
    assert f'/marriage-checklist?session={sid}' in rows[0]['payload']['html']


def test_a_checklist_player_gets_their_summary_with_the_stored_wording(client, make_person, sign_in,
                                                                        switches):
    owner = _mailable(make_person, 'Daniel')
    sid, token, _ = _start(client, sign_in(owner), mode='single', kind='checklist')
    _play(client, sid, token, {'p1': dict(section='biblical', importance=5, stance='agree')},
          role='husband')
    rows = [r for r in _rows(sid) if r['campaign'] == mail.CAMPAIGN_SUMMARY]
    assert len(rows) == 1 and rows[0]['person_id'] == owner['id']
    html = rows[0]['payload']['html']
    assert STORED_LINE in html and 'never stored' not in html and 'Genesis 2:18-24' in html
    assert 'We sent the same note to you and your spouse' not in html


def test_a_visitor_who_saves_after_finishing_gets_their_summary(client, tool_visitor, switches,
                                                                 monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    _, headers = tool_visitor()
    body = client.post('/tools/sessions', json=dict(kind='checklist', mode='single')).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    _play(client, sid, token, {'p1': dict(section='biblical', importance=5, stance='agree')},
          role='wife')
    assert _rows(sid) == []
    client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Rivka'), headers=_h(token, headers))
    rows = _rows(sid)
    assert [r['campaign'] for r in rows] == [mail.CAMPAIGN_SUMMARY] and rows[0]['lead_id']


def test_the_first_checklist_summary_is_unchanged():
    html = checklist_results_html('wife', [dict(section='biblical', ref='Hebrews 13:4',
                                                importance=5, stance='agree')])
    assert 'We never stored your answers' in html
    assert 'We sent the same note to you and your spouse' in html


def test_names_are_escaped_in_every_email():
    html = mail.answered_html('R&D <x>', 'https://ahavah.app/together/game', 'https://ahavah.app/u/t')
    assert 'R&amp;D &lt;x&gt; has answered. See how you fit.' in html and '<x>' not in html
    for kind in ('game', 'checklist'):
        html = mail.invite_html(kind, 'R&D', 'https://ahavah.app/tools/i/t')
        assert 'R&amp;D' in html and 'R&D' not in html.replace('R&amp;D', '')
    assert mail.invite_subject('game', 'Rivka') == 'Rivka wants to see how well you fit'
    assert mail.invite_subject('checklist', 'Rivka') == 'Rivka invited you to the Ahavah marriage checklist'


def test_a_failure_to_queue_never_breaks_finishing(client, make_person, sign_in, switches,
                                                    monkeypatch):
    monkeypatch.setattr(mail, '_recipient', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom')))
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    r = _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert r.status_code == 200 and r.get_json()['state'] == 'ready'
    assert _rows(sid) == []


def test_the_api_says_where_the_checklist_v2_stores_answers():
    import inspect

    from service import person
    doc = inspect.getdoc(person.post_marriage_checklist_send)
    assert 'service/tools' in doc and 'never persisted' not in doc
