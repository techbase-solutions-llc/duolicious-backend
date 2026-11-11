"""The inbox drops reported and gone members (11 Nov 2026).

Q_GET_INBOX only dropped threads across the tester line, so a thread with
someone reported or blocked, deactivated or waiting to be deleted stayed
in the inbox and its unread messages stayed in the badge (the web sums
the inbox's unread counts). Those threads are now hidden, never deleted,
and the unread-message push and email leave them out too. A plain pass
hides nothing.
"""
from __future__ import annotations

import pytest

from database import api_tx
from tests.unmatch_helpers import converse


@pytest.fixture
def pair(make_person):
    me = make_person(name='InbMe', gender='Woman')
    peer = make_person(name='InbPeer', gender='Man')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[me['id'], peer['id']]))
    converse(peer, me, 'Shalom')
    yield me, peer
    with api_tx() as tx:
        tx.execute("DELETE FROM inbox WHERE luser = ANY(%(u)s) "
                   "OR split_part(remote_bare_jid, '@', 1) = ANY(%(u)s)",
                   dict(u=[me['uuid'], peer['uuid']]))


def _inbox(me):
    from service.chat.messagestorage.inbox import Q_GET_INBOX
    with api_tx() as tx:
        return {r['remote_bare_jid'].split('@')[0]: r['unread_count']
                for r in tx.execute(Q_GET_INBOX, dict(username=me['uuid'])).fetchall()}


def _due_for_unread_push(me) -> bool:
    from service.cron.notifications.sql import Q_UNREAD_INBOX
    with api_tx() as tx:
        tx.execute("""UPDATE inbox SET timestamp = EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')::bigint * 1000000
                       WHERE luser = %(u)s""", dict(u=me['uuid']))
        tx.execute("UPDATE person SET last_online_time = NOW() - INTERVAL '2 hours' WHERE id = %(i)s",
                   dict(i=me['id']))
        return me['uuid'] in {str(r['person_uuid']) for r in tx.execute(Q_UNREAD_INBOX).fetchall()}


def test_a_live_thread_shows_with_its_unread_count(pair):
    me, peer = pair
    assert _inbox(me) == {peer['uuid']: 1}
    assert _due_for_unread_push(me)


def test_a_plain_pass_hides_nothing(pair):
    me, peer = pair
    with api_tx() as tx:
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                   'VALUES (%(a)s, %(b)s, FALSE)', dict(a=me['id'], b=peer['id']))
    assert peer['uuid'] in _inbox(me)


@pytest.mark.parametrize('how', ['reported_by_me', 'reported_me', 'deactivated', 'deletion_requested'])
def test_a_thread_with_someone_reported_or_gone_is_hidden_and_kept(pair, how):
    me, peer = pair
    with api_tx() as tx:
        if how == 'reported_by_me':
            tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                       'VALUES (%(a)s, %(b)s, TRUE)', dict(a=me['id'], b=peer['id']))
        elif how == 'reported_me':
            tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                       'VALUES (%(a)s, %(b)s, TRUE)', dict(a=peer['id'], b=me['id']))
        elif how == 'deactivated':
            tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=peer['id']))
        else:
            tx.execute('UPDATE person SET deletion_requested_at = NOW() WHERE id = %(i)s',
                       dict(i=peer['id']))
    assert peer['uuid'] not in _inbox(me)
    assert not _due_for_unread_push(me)
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM inbox WHERE luser = %(u)s', dict(u=me['uuid'])).fetchone()
