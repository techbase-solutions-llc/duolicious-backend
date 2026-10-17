"""Together's retention (TEC-1845).

Spec: "Rows are deleted 12 months after the last visit, or on request."
A session nobody saved goes after 30 days (nothing links it to anyone but
a device); a deleted session's tombstone goes 30 days after the delete.
Deleting an account deletes every session the address saved and every Us
game or couple checklist it joined, since a comparison is shared.
"""
from __future__ import annotations

import pathlib
import secrets

import pytest

from database import api_tx
from service.hard_delete import Q_DELETE_TOOL_DATA_OF
from service.tools.retention import purge_stale_tool_sessions

pytestmark = pytest.mark.usefixtures('together_schema')


def _session(*, mode='us', saved=True, days_ago=0, deleted_days_ago=None, owner_ne=None,
             owner_person_id=None) -> int:
    kind = 'checklist' if mode in ('couple', 'single') else 'game'
    source = {'me': 'tool:game-me', 'us': 'tool:game-us', 'knows_me': 'tool:knows-me',
              'couple': 'tool:checklist', 'single': 'tool:checklist'}[mode]
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO tool_session (kind, mode, source, claimed_at, last_visit_at, deleted_at,
                                         owner_normalized_email, owner_person_id)
               VALUES (%(k)s, %(m)s, %(src)s, CASE WHEN %(saved)s THEN NOW() END,
                       NOW() - make_interval(days => %(d)s),
                       CASE WHEN %(dd)s::int IS NOT NULL
                            THEN NOW() - make_interval(days => %(dd)s) END,
                       %(ne)s, %(pid)s)
               RETURNING id""",
            dict(k=kind, m=mode, src=source, saved=saved, d=days_ago, dd=deleted_days_ago,
                 ne=owner_ne, pid=owner_person_id)).fetchone()['id']


def _exists(ids):
    with api_tx() as tx:
        return [bool(tx.execute('SELECT 1 FROM tool_session WHERE id = %(i)s', dict(i=i)).fetchone())
                for i in ids]


def _drop(ids):
    with api_tx() as tx:
        tx.execute('DELETE FROM tool_session WHERE id = ANY(%(i)s)', dict(i=list(ids)))


def test_the_sweep_keeps_what_is_recent_and_deletes_what_is_old(make_person):
    member = make_person(name='Keeper')
    keep = [_session(days_ago=364), _session(saved=False, days_ago=29),
            _session(saved=False, days_ago=31, owner_person_id=member['id']),
            _session(days_ago=1, deleted_days_ago=29)]
    gone = [_session(days_ago=366), _session(saved=False, days_ago=31),
            _session(days_ago=1, deleted_days_ago=31)]
    try:
        with api_tx() as tx:
            purge_stale_tool_sessions(tx)
        assert _exists(keep) == [True] * 4 and _exists(gone) == [False] * 3
    finally:
        _drop(keep + gone)


def test_the_daily_cron_runs_the_sweep():
    from service.cron import leadretention
    old = _session(days_ago=400)
    try:
        leadretention._purge_once()
        assert _exists([old]) == [False]
    finally:
        _drop([old])


def test_deleting_an_account_deletes_the_sessions_it_saved_or_shared():
    ne = f'gone-{secrets.token_hex(5)}@ahavah-test.invalid'
    owned = _session(mode='me', owner_ne=ne)
    joined = _session(mode='us')
    friend = _session(mode='knows_me')
    with api_tx() as tx:
        for sid in (joined, friend):
            tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, normalized_email)
                          VALUES (%(s)s, 'guest', %(h)s, %(ne)s)""",
                       dict(s=sid, h=secrets.token_hex(16), ne=ne))
    try:
        with api_tx() as tx:
            tx.execute(Q_DELETE_TOOL_DATA_OF, dict(nes=[ne], ids=[]))
        assert _exists([owned, joined, friend]) == [False, False, True]
    finally:
        _drop([owned, joined, friend])


def test_both_deletion_paths_run_it():
    for path in ('service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        assert 'Q_DELETE_TOOL_DATA_OF' in pathlib.Path(f'/app/{path}').read_text(), path


# Review, 17 Oct 2026: both deletion paths deleted the person first, and
# tool_player.person_id cascades, so the guest's seat went before
# Q_DELETE_TOOL_DATA_OF could find the shared game by it. The game stayed
# with its result, the couple owner's view failed and the seat reopened.

def _seat(sid, *, seat='guest', ne=None, pid=None, display='Rivka') -> int:
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO tool_player (session_id, seat, token_hash, display, normalized_email,
                                        person_id, finished_at)
               VALUES (%(s)s, %(seat)s, %(h)s, %(d)s, %(ne)s, %(pid)s, NOW())
               RETURNING id""",
            dict(s=sid, seat=seat, h=secrets.token_hex(16), d=display, ne=ne, pid=pid)
        ).fetchone()['id']


def _shared_games_of(leaver: dict) -> dict:
    """An Us game the leaver joined with their address and account, a couple
    checklist they joined linked by account only (saved with an address
    typed another way), and a knows-me board they are on."""
    from antiabuse.antispam.signupemail import normalize_email
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(p)s',
                           dict(p=leaver['id'])).fetchone()['email']
    ne = normalize_email(email)
    other = f'owner-{secrets.token_hex(5)}@ahavah-test.invalid'
    games = dict(us=_session(mode='us', owner_ne=other),
                 couple=_session(mode='couple', owner_ne=other),
                 knows_me=_session(mode='knows_me', owner_ne=other))
    for mode, sid in games.items():
        _seat(sid, seat='owner', display=None)
        _seat(sid, ne=ne if mode == 'us' else None, pid=leaver['id'])
    with api_tx() as tx:
        tx.execute("""INSERT INTO tool_result (session_id, score, breakdown)
                      VALUES (%(s)s, 80, '{}'::jsonb)""", dict(s=games['us']))
        tx.execute('UPDATE tool_session SET completed_at = NOW() WHERE id = ANY(%(i)s)',
                   dict(i=[games['us'], games['couple']]))
    return games


def _assert_shared_games_gone(games: dict, leaver: dict) -> None:
    assert _exists([games['us'], games['couple'], games['knows_me']]) == [False, False, True], \
        'an Us game or couple checklist the deleted member joined survived'
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM tool_player WHERE person_id = %(p)s',
                          dict(p=leaver['id'])).fetchone() is None


def test_the_deletion_cron_deletes_the_shared_games_a_guest_joined(make_person):
    import asyncio

    from service.cron.pendingdeletion import hard_delete_expired_once
    leaver = make_person(name='GuestLeaver')
    games = _shared_games_of(leaver)
    with api_tx() as tx:
        tx.execute("""UPDATE person SET activated = FALSE,
                             deletion_requested_at = NOW() - INTERVAL '8 days',
                             sign_in_time = NOW() - INTERVAL '9 days'
                       WHERE id = %(p)s""", dict(p=leaver['id']))
    try:
        asyncio.run(hard_delete_expired_once())
        _assert_shared_games_gone(games, leaver)
    finally:
        _drop(games.values())


def test_the_admin_hard_delete_deletes_the_shared_games_a_guest_joined(make_person, client):
    import hashlib
    admin = make_person(name='ToolDeleteAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        admin_email = tx.execute(
            "UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s RETURNING email",
            dict(i=admin['id'])).fetchone()['email']
        tx.execute("""INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
                      VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
                   dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=admin_email, p=admin['id']))
    leaver = make_person(name='GuestLeaver')
    games = _shared_games_of(leaver)
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(p)s',
                           dict(p=leaver['id'])).fetchone()['email']
    try:
        r = client.delete(f"/admin/users/{leaver['uuid']}",
                          json={'confirm_email': email, 'reason': 'test'},
                          headers={'Authorization': f'Bearer {tok}'})
        assert r.status_code == 200, r.get_data(as_text=True)
        _assert_shared_games_gone(games, leaver)
    finally:
        _drop(games.values())


@pytest.mark.usefixtures('together_live', 'no_limits')
@pytest.mark.parametrize('mode,kind', [('us', 'game'), ('couple', 'checklist')])
def test_a_finished_shared_game_whose_guest_is_gone_stays_closed(client, mode, kind):
    """However a guest's seat goes, the owner's view still answers and the
    seat does not reopen for a stranger to see the old result."""
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    sid, owner = body['session_id'], body['player_token']
    invite = secrets.token_urlsafe(16)
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET invite_token = %(t)s, owner_display = 'Daniel',
                             claimed_at = NOW() WHERE uuid = %(u)s""", dict(t=invite, u=sid))
    answers = ({'calendar': 'enoch'} if kind == 'game'
               else {'p1': dict(section='biblical', importance=4, stance='agree')})

    def play(token, role):
        items = [dict(question_key=k, answer=v) for k, v in answers.items()]
        client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, role=role),
                    headers={'X-Tool-Token': token})
        return client.post(f'/tools/sessions/{sid}/finish', headers={'X-Tool-Token': token})

    try:
        play(owner, 'husband' if kind == 'checklist' else None)
        guest = client.post(f'/tools/i/{invite}/players',
                            json=dict(display='Rivka')).get_json()['player_token']
        assert play(guest, 'wife' if kind == 'checklist' else None).get_json()['state'] == 'ready'
        with api_tx() as tx:
            tx.execute("""DELETE FROM tool_player WHERE seat = 'guest' AND session_id =
                            (SELECT id FROM tool_session WHERE uuid = %(u)s)""", dict(u=sid))
        r = client.get(f'/tools/sessions/{sid}', headers={'X-Tool-Token': owner})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['guest_display'] is None
        assert client.get(f'/tools/i/{invite}').get_json()['state'] == 'full'
        j = client.post(f'/tools/i/{invite}/players', json=dict(display='Stranger'))
        assert (j.status_code, j.get_json()) == (409, {'error': 'full'})
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
