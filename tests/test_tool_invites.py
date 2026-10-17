"""Together's second player (TEC-1845).

An Us game and a couple checklist take one guest; the first keeps the
seat. Knows-me takes many friends, each giving only a display name, once
the player has answered. A friend sees their score and the board, never
the player's answers (owner decision 6). The player cannot join their own
game. A signed-in member joins with no email step.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from database import api_tx

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


def _h(token):
    return {'X-Tool-Token': token}


def _play(client, sid, token, answers):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items), headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _open(client, mode='us', kind='game', owner_answers=None, finish=True, email=None):
    r = client.post('/tools/sessions', json=dict(kind=kind, mode=mode))
    sid, token = r.get_json()['session_id'], r.get_json()['player_token']
    _MADE.append(sid)
    if finish:
        _play(client, sid, token, owner_answers or {})
    invite = secrets.token_urlsafe(16)
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET invite_token = %(t)s, share_token = %(st)s,
                             owner_display = 'Daniel', claimed_at = NOW(),
                             owner_email = %(e)s, owner_normalized_email = %(e)s
                       WHERE uuid = %(u)s""",
                   dict(t=invite, st=secrets.token_urlsafe(16), e=email, u=sid))
    return sid, token, invite


def _join(client, invite, display='Rivka', headers=None):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display),
                       headers=headers or {})


def test_an_invite_link_says_who_invited_and_whether_it_is_open(client):
    _, _, invite = _open(client)
    assert client.get(f'/tools/i/{invite}').get_json() == {
        'kind': 'game', 'mode': 'us', 'owner_display': 'Daniel', 'state': 'open'}


def test_an_unknown_or_malformed_link_is_not_found(client):
    for token in ('x', secrets.token_urlsafe(16), 'a' * 200):
        assert client.get(f'/tools/i/{token}').status_code == 404


def test_a_deleted_game_says_so(client):
    sid, _, invite = _open(client)
    with api_tx() as tx:
        tx.execute('UPDATE tool_session SET deleted_at = NOW() WHERE uuid = %(u)s', dict(u=sid))
    r = client.get(f'/tools/i/{invite}')
    assert (r.status_code, r.get_json()) == (410, {'error': 'deleted'})
    assert _join(client, invite).status_code == 410


def test_a_guest_joins_with_a_name_and_plays(client):
    sid, _, invite = _open(client)
    r = _join(client, invite, display='  Rivka ')
    assert r.status_code == 201
    body = r.get_json()
    assert body['session_id'] == sid and len(body['player_token']) == 32
    v = client.get(f'/tools/sessions/{sid}', headers=_h(body['player_token'])).get_json()
    assert (v['seat'], v['my_display'], v['guest_display'], v['claimed']) == (
        'guest', 'Rivka', 'Rivka', False)


def test_a_second_guest_is_refused_in_a_two_player_mode(client):
    _, _, invite = _open(client)
    assert _join(client, invite).status_code == 201
    r = _join(client, invite, display='Leah')
    assert (r.status_code, r.get_json()) == (409, {'error': 'full'})
    assert client.get(f'/tools/i/{invite}').get_json()['state'] == 'full'


def test_the_owner_cannot_join_their_own_game(client, tool_visitor):
    email, headers = tool_visitor()
    _, _, invite = _open(client, email=email)
    r = _join(client, invite, headers=headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'own_session'})


def test_a_signed_in_member_joins_with_no_email_step(client, make_person, sign_in):
    member = make_person(name='Samuel')
    sid, _, invite = _open(client)
    token = _join(client, invite, display='Samuel', headers=sign_in(member)).get_json()['player_token']
    v = client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()
    assert v['claimed'] is True and v['member'] is True


def test_friends_need_the_player_to_have_finished_and_never_see_their_answers(client):
    owner_answers = CASES['order-matters']['owner']
    _, _, early = _open(client, mode='knows_me', finish=False)
    r = _join(client, early, display='Hannah')
    assert (r.status_code, r.get_json()) == (409, {'error': 'not_ready'})
    sid, owner, invite = _open(client, mode='knows_me', owner_answers=owner_answers)
    hannah = _join(client, invite, display='Hannah').get_json()['player_token']
    josiah = _join(client, invite, display='Josiah').get_json()['player_token']
    _play(client, sid, hannah, owner_answers | {'country': 'BB'})
    _play(client, sid, josiah, owner_answers | {'country': 'BB', 'move': 'local-only'})
    h = client.get(f'/tools/sessions/{sid}', headers=_h(hannah)).get_json()
    assert h['result'] == {'right': 13, 'total': 14, 'place': 1}
    assert h['board'] == [dict(display='Hannah', right=13, total=14, me=True),
                          dict(display='Josiah', right=12, total=14, me=False)]
    assert '"JM"' not in json.dumps(h), 'a friend must never read the player answers'
    o = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()
    assert [(b['display'], b['removed']) for b in o['board']] == [('Hannah', False), ('Josiah', False)]


def test_the_owner_removes_and_restores_a_name(client):
    sid, owner, invite = _open(client, mode='knows_me', owner_answers={'calendar': 'enoch'})
    friend = _join(client, invite, display='Josiah').get_json()['player_token']
    _play(client, sid, friend, {'calendar': 'enoch'})
    gid = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()['board'][0]['player_id']
    assert client.delete(f'/tools/sessions/{sid}/players/{gid}', headers=_h(friend)).status_code == 403
    o = client.delete(f'/tools/sessions/{sid}/players/{gid}', headers=_h(owner)).get_json()
    assert o['board'][0]['removed'] is True
    assert client.get(f'/tools/sessions/{sid}', headers=_h(friend)).get_json()['board'] == []
    o = client.post(f'/tools/sessions/{sid}/players/{gid}/restore', headers=_h(owner)).get_json()
    assert o['board'][0]['removed'] is False


# Review, 17 Oct 2026: each join issued a fresh seat, and a finished friend
# sees right or wrong per question, so one person could re-join and read
# the player's answers a question at a time.

def test_one_network_joins_an_invite_at_most_3_times_a_day(client):
    sid, _, invite = _open(client, mode='knows_me', owner_answers={'calendar': 'enoch'})

    def join_from(ip, n, link=invite):
        return client.post(f'/tools/i/{link}/players', json=dict(display=f'Friend {n}'),
                           environ_base={'REMOTE_ADDR': ip})

    for n in range(3):
        assert join_from('203.0.113.7', n).status_code == 201
    r = join_from('203.0.113.99', 4)  # the same /24
    assert (r.status_code, r.get_json()) == (429, {'error': 'too_many_joins'})
    assert join_from('198.51.100.4', 5).status_code == 201
    _, _, other = _open(client, mode='knows_me', owner_answers={'calendar': 'enoch'})
    assert join_from('203.0.113.7', 6, other).status_code == 201
    with api_tx() as tx:
        tx.execute("""UPDATE tool_player SET created_at = NOW() - INTERVAL '25 hours'
                       WHERE session_id = (SELECT id FROM tool_session WHERE uuid = %(u)s)""",
                   dict(u=sid))
    assert join_from('203.0.113.7', 7).status_code == 201


def test_a_friend_finishes_only_once_every_scored_question_is_answered(client):
    owner_answers = {'calendar': 'enoch', 'move': 'local-only', 'sabbath-afternoon': 'walk'}
    sid, _, invite = _open(client, mode='knows_me', owner_answers=owner_answers)
    friend = _join(client, invite, display='Hannah').get_json()['player_token']
    r = _play(client, sid, friend, {'calendar': 'enoch'})
    assert (r.status_code, r.get_json()) == (409, {'error': 'unanswered'})
    v = client.get(f'/tools/sessions/{sid}', headers=_h(friend)).get_json()
    assert (v['state'], v['result']) == ('playing', None)
    r = _play(client, sid, friend, {'move': 'will-relocate'})
    assert r.status_code == 200
    assert r.get_json()['result'] == {'right': 1, 'total': 2, 'place': 1}
