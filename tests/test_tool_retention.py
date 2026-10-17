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
            tx.execute(Q_DELETE_TOOL_DATA_OF, dict(nes=[ne]))
        assert _exists([owned, joined, friend]) == [False, False, True]
    finally:
        _drop([owned, joined, friend])


def test_both_deletion_paths_run_it():
    for path in ('service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        assert 'Q_DELETE_TOOL_DATA_OF' in pathlib.Path(f'/app/{path}').read_text(), path
