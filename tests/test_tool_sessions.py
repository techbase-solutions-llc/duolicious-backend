"""Together sessions: start, answer, finish and read (TEC-1845).

Playing needs no account. The device's X-Tool-Token is the player; a
saved player may also come back signed in with that address. Nothing of
an Us game shows until both have answered, and neither player ever reads
the other's answers.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from database import api_tx
from service.leads import new_token

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _start(client, mode='us', kind='game', headers=None):
    r = client.post('/tools/sessions', json=dict(kind=kind, mode=mode), headers=headers or {})
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    _MADE.append(body['session_id'])
    return body['session_id'], body['player_token']


def _h(token):
    return {'X-Tool-Token': token}


def _answer(client, sid, token, answers: dict, **extra):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    return client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, **extra),
                       headers=_h(token))


def _finish(client, sid, token):
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _add_guest(sid, display='Rivka') -> str:
    token, hashed = new_token()
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO tool_player (session_id, seat, token_hash, display)
               SELECT id, 'guest', %(h)s, %(d)s FROM tool_session WHERE uuid = %(u)s""",
            dict(h=hashed, d=display, u=sid))
    return token


def test_every_tool_route_is_dark_until_live(client, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOGETHER_LIVE_ENABLED', raising=False)
    r = client.post('/tools/sessions', json=dict(kind='game', mode='me'))
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})
    sid = str(uuid.uuid4())
    assert client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=[])).status_code == 404
    assert client.get(f'/tools/sessions/{sid}').status_code == 404


def test_a_visitor_starts_a_game_with_no_account(client):
    sid, token = _start(client)
    assert str(uuid.UUID(sid)) == sid and len(token) == 32
    with api_tx() as tx:
        s = tx.execute("""SELECT kind, mode, source, owner_person_id, claimed_at
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
        p = tx.execute("""SELECT seat, token_hash FROM tool_player
                           WHERE session_id = (SELECT id FROM tool_session WHERE uuid = %(u)s)""",
                       dict(u=sid)).fetchone()
    assert dict(s) == dict(kind='game', mode='us', source='tool:game-us', owner_person_id=None,
                           claimed_at=None)
    assert p['seat'] == 'owner' and p['token_hash'] != token


def test_a_bad_mode_is_refused(client):
    r = client.post('/tools/sessions', json=dict(kind='game', mode='couple'))
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_mode'})
    assert client.post('/tools/sessions', json=dict(kind='game', mode='dating')).status_code == 400


def test_answers_need_the_players_token(client):
    sid, _ = _start(client)
    assert client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=[])).status_code == 404
    assert _answer(client, sid, 'x' * 32, {'calendar': 'enoch'}).status_code == 404
    assert client.get('/tools/sessions/not-a-uuid', headers=_h('x' * 32)).status_code == 404


def test_an_answer_is_checked_saved_and_skipped(client):
    sid, token = _start(client)
    r = _answer(client, sid, token, {'calendar': 'enoch'})
    assert (r.status_code, r.get_json()) == (200, {'saved': 1})
    bad = _answer(client, sid, token, {'calendar': 'julian'})
    assert (bad.status_code, bad.get_json()) == (400, {'error': 'bad_answer'})
    assert _answer(client, sid, token, {'calendar': None}).status_code == 200
    assert client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()['my_answers'] == {}


def test_a_finished_player_cannot_change_answers(client):
    sid, token = _start(client, mode='me')
    _answer(client, sid, token, {'calendar': 'enoch'})
    assert _finish(client, sid, token).status_code == 200
    r = _answer(client, sid, token, {'calendar': 'other'})
    assert (r.status_code, r.get_json()) == (409, {'error': 'finished'})


def test_me_finishes_with_its_archetype(client):
    sid, token = _start(client, mode='me')
    _answer(client, sid, token, CASES['identical']['owner'])
    v = _finish(client, sid, token).get_json()
    assert v['state'] == 'ready'
    assert v['result'] == {'archetype': 'feast', 'why': ['feast', 'family']}
    assert v['share_token'] is None and v['claimed'] is False


def test_us_reveals_nothing_until_both_have_finished(client):
    case = CASES['order-matters']
    sid, owner = _start(client)
    _answer(client, sid, owner, case['owner'])
    v = _finish(client, sid, owner).get_json()
    assert (v['state'], v['result']) == ('waiting', None)
    guest = _add_guest(sid)
    g = client.get(f'/tools/sessions/{sid}', headers=_h(guest)).get_json()
    assert (g['seat'], g['state'], g['my_answers'], g['result']) == ('guest', 'playing', {}, None)
    _answer(client, sid, guest, case['guest'])
    g = _finish(client, sid, guest).get_json()
    o = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()
    for view in (g, o):
        assert view['state'] == 'ready'
        assert view['result']['score'] == 59
        assert view['result']['align'] == ['relocation', 'language', 'observance']
        assert (view['owner_display'], view['guest_display']) == (None, 'Rivka')
    assert o['my_answers'] == case['owner'] and g['my_answers'] == case['guest']
    assert 'wants-partner-willing' not in json.dumps(g), 'the guest must never read the owner answers'
    with api_tx() as tx:
        n = tx.execute("""SELECT count(*) AS n FROM tool_result
                           WHERE session_id = (SELECT id FROM tool_session WHERE uuid = %(u)s)""",
                       dict(u=sid)).fetchone()['n']
    assert n == 1


def test_a_member_who_starts_owns_the_session(client, make_person, sign_in):
    member = make_person(name='ToolMember')
    sid, token = _start(client, mode='me', headers=sign_in(member))
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
    assert owner == member['id']
    assert client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()['member'] is True


def _saved_by(sid, email):
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET owner_email = %(e)s, owner_normalized_email = %(e)s,
                             owner_display = 'Daniel', claimed_at = NOW()
                       WHERE uuid = %(u)s""", dict(e=email, u=sid))


def test_a_signed_in_player_can_reopen_with_their_email(client, tool_visitor):
    email, headers = tool_visitor()
    sid, _ = _start(client)
    _saved_by(sid, email)
    r = client.get(f'/tools/sessions/{sid}', headers=headers)
    assert r.status_code == 200 and r.get_json()['seat'] == 'owner'


def test_someone_elses_session_never_opens(client, tool_visitor):
    email, _ = tool_visitor()
    _, stranger = tool_visitor()
    sid, _ = _start(client)
    _saved_by(sid, email)
    assert client.get(f'/tools/sessions/{sid}', headers=stranger).status_code == 404


def test_a_display_name_is_cleaned_or_refused():
    from service.tools.sessions import ToolError, clean_display
    assert clean_display('  Rivka   Ann ') == 'Rivka Ann'
    assert clean_display('R.') == 'R.'
    for bad in ('', '   ', 'x' * 41, 'Ri\x07', '<b>R</b>', 'Ri\nka', None, 7):
        with pytest.raises(ToolError, match='bad_display'):
            clean_display(bad)
