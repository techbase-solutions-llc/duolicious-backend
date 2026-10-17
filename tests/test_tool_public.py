"""Together's public summary and deleting (TEC-1845).

Spec: "GET /tools/r/{share_token}: public summary for the result page and
image; no answers." "No answers are ever on public cards." "Either person
can delete the shared comparison." A deleted result keeps only its tokens,
so every link to it says it was deleted.
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


def _play(client, sid, token, answers, role=None):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, role=role),
                headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token)).get_json()


def _saved(client, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    share, invite = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET share_token = %(s)s, invite_token = %(i)s,
                             owner_display = 'Daniel', claimed_at = NOW()
                       WHERE uuid = %(u)s""", dict(s=share, i=invite, u=sid))
    return sid, token, share, invite


def _guest(client, invite, display='Rivka'):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display)).get_json()['player_token']


def test_the_public_summary_never_carries_an_answer(client):
    case = CASES['order-matters']
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, case['owner'])
    _play(client, sid, _guest(client, invite), case['guest'])
    body = client.get(f'/tools/r/{share}').get_json()
    assert body == {'kind': 'game', 'mode': 'us', 'names': ['Daniel', 'Rivka'], 'state': 'ready',
                    'score': 59}
    text = json.dumps(body)
    for value in ('enoch', 'JM', 'wants-partner-willing', 'relocation', 'align'):
        assert value not in text


def test_us_shows_no_score_until_both_have_finished(client):
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, {'calendar': 'enoch'})
    _guest(client, invite)
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'game', 'mode': 'us', 'names': ['Daniel', 'Rivka'], 'state': 'waiting'}


def test_me_shows_the_archetype_and_one_name(client):
    sid, owner, share, _ = _saved(client, mode='me')
    _play(client, sid, owner, CASES['identical']['owner'])
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'game', 'mode': 'me', 'names': ['Daniel'], 'state': 'ready', 'archetype': 'feast'}


def test_knows_me_shows_only_the_player_never_a_friend(client):
    sid, owner, share, invite = _saved(client, mode='knows_me')
    _play(client, sid, owner, {'calendar': 'enoch'})
    _play(client, sid, _guest(client, invite, 'Hannah'), {'calendar': 'enoch'})
    body = client.get(f'/tools/r/{share}').get_json()
    assert body == {'kind': 'game', 'mode': 'knows_me', 'names': ['Daniel'], 'state': 'ready'}


def test_a_checklist_couple_shows_agreement_counts(client):
    sid, owner, share, invite = _saved(client, mode='couple', kind='checklist')
    item = dict(section='biblical', importance=4, stance='agree')
    _play(client, sid, owner, {'p1': item, 'p3': item}, role='husband')
    _play(client, sid, _guest(client, invite), {'p1': item, 'p3': dict(item, stance='other')},
          role='wife')
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'checklist', 'mode': 'couple', 'names': ['Daniel', 'Rivka'], 'state': 'ready',
        'agree': 1, 'total': 2}


def test_unknown_malformed_and_deleted_links(client):
    assert client.get('/tools/r/x').status_code == 404
    assert client.get(f'/tools/r/{secrets.token_urlsafe(16)}').status_code == 404
    sid, owner, share, _ = _saved(client, mode='me')
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(owner)).status_code == 204
    r = client.get(f'/tools/r/{share}')
    assert (r.status_code, r.get_json(), r.headers['Cache-Control']) == (
        410, {'error': 'deleted'}, 'no-store')


def test_opening_a_share_link_is_counted(client):
    _, _, share, _ = _saved(client, mode='me')
    assert client.post(f'/tools/r/{share}/open').status_code == 204
    client.post(f'/tools/r/{share}/open')
    with api_tx() as tx:
        n = tx.execute('SELECT share_opens FROM tool_session WHERE share_token = %(s)s',
                       dict(s=share)).fetchone()['share_opens']
    assert n == 2


def test_deleting_leaves_only_a_tombstone(client):
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, {'calendar': 'enoch'})
    guest = _guest(client, invite)
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(owner)).status_code == 204
    with api_tx() as tx:
        s = tx.execute("""SELECT id, owner_email, owner_display, deleted_at IS NOT NULL AS gone
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
        left = [tx.execute(f'SELECT count(*) AS n FROM {t} WHERE session_id = %(s)s',
                           dict(s=s['id'])).fetchone()['n'] for t in ('tool_answer', 'tool_result')]
        names = tx.execute("""SELECT count(*) AS n FROM tool_player
                               WHERE session_id = %(s)s AND (display IS NOT NULL OR email IS NOT NULL)""",
                           dict(s=s['id'])).fetchone()['n']
    assert (s['owner_email'], s['owner_display'], s['gone'], left, names) == (None, None, True, [0, 0], 0)
    for r in (client.get(f'/tools/sessions/{sid}', headers=_h(guest)), client.get(f'/tools/r/{share}'),
              client.get(f'/tools/i/{invite}')):
        assert (r.status_code, r.get_json()) == (410, {'error': 'deleted'})


def test_either_player_deletes_a_two_player_result_but_a_friend_cannot(client):
    sid, _, _, invite = _saved(client)
    guest = _guest(client, invite)
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(guest)).status_code == 204
    sid2, owner2, _, invite2 = _saved(client, mode='knows_me')
    _play(client, sid2, owner2, {'calendar': 'enoch'})
    friend = _guest(client, invite2, 'Hannah')
    r = client.delete(f'/tools/sessions/{sid2}', headers=_h(friend))
    assert (r.status_code, r.get_json()) == (403, {'error': 'not_allowed'})
