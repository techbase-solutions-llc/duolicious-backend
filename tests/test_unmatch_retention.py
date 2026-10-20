"""The hold on an unmatched conversation (TEC-1845, migration 0070) ends:
the daily retention cron deletes it after HOLD_DAYS, and a hard delete of
either person takes both sides of it at once. Voice notes go to the CDN
cleaner's queue either way. A staged uuid here names no real file, so each
test takes its own back out of the queue."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from database import api_tx
from service.decisions.unmatch import purge_held_messages
from service.hard_delete import Q_PURGE_HELD_MESSAGES_OF
from tests.unmatch_helpers import converse, counts, match

pytestmark = pytest.mark.usefixtures('no_limits')


def _unmatch(client, p) -> None:
    assert client.post(f'/unmatch/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200


def _staged(tx, audio_uuid: str) -> bool:
    found = tx.execute('SELECT 1 FROM undeleted_audio WHERE uuid = %(u)s', dict(u=audio_uuid)).fetchone()
    tx.execute('DELETE FROM undeleted_audio WHERE uuid = %(u)s', dict(u=audio_uuid))
    return found is not None


def test_held_messages_go_when_the_hold_ends(client, unmatch_pair):
    p = unmatch_pair
    voice = f'test-voice-{uuid4().hex}'
    match(p.a, p.b)
    converse(p.a, p.b, 'A voice note', audio_uuid=voice)
    converse(p.b, p.a, 'Still held')
    _unmatch(client, p)
    with api_tx() as tx:
        tx.execute("""UPDATE unmatched_message SET held_until = NOW() - interval '1 minute'
                       WHERE audio_uuid = %(v)s""", dict(v=voice))
        n = purge_held_messages(tx)
        staged = _staged(tx, voice)

    assert n >= 2
    assert counts(p.a, p.b)['held'] == 2
    assert staged


def test_a_hard_delete_takes_both_sides_of_the_held_conversation(client, unmatch_pair):
    p = unmatch_pair
    voice = f'test-voice-{uuid4().hex}'
    match(p.a, p.b)
    converse(p.a, p.b, 'A voice note', audio_uuid=voice)
    converse(p.b, p.a, 'A reply')
    _unmatch(client, p)
    with api_tx() as tx:
        tx.execute(Q_PURGE_HELD_MESSAGES_OF, dict(ids=[p.a['id']], uuids=[p.a['uuid']]))
        staged = _staged(tx, voice)

    assert counts(p.a, p.b)['held'] == 0
    assert staged


def test_both_deletion_paths_purge_the_hold():
    for path in ('service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        assert 'Q_PURGE_HELD_MESSAGES_OF' in Path(f'/app/{path}').read_text(), path


def test_the_daily_retention_cron_purges_the_hold():
    assert 'purge_held_messages' in Path('/app/service/cron/leadretention/__init__.py').read_text()


def _hold_with_a_voice_note(client, p) -> str:
    voice = f'test-voice-{uuid4().hex}'
    match(p.a, p.b)
    converse(p.a, p.b, 'A voice note', audio_uuid=voice)
    converse(p.b, p.a, 'A reply')
    _unmatch(client, p)
    assert counts(p.a, p.b)['held'] == 4
    return voice


def test_the_deletion_cron_takes_both_sides_of_the_held_conversation(client, unmatch_pair):
    import asyncio

    from service.cron.pendingdeletion import hard_delete_expired_once

    p = unmatch_pair
    voice = _hold_with_a_voice_note(client, p)
    with api_tx() as tx:
        tx.execute("""UPDATE person SET activated = FALSE,
                             deletion_requested_at = NOW() - interval '8 days',
                             sign_in_time = NOW() - interval '9 days'
                       WHERE id = %(p)s""", dict(p=p.a['id']))

    asyncio.run(hard_delete_expired_once())

    with api_tx() as tx:
        staged = _staged(tx, voice)
    assert counts(p.a, p.b)['held'] == 0
    assert staged


def test_the_admin_hard_delete_takes_both_sides_however_the_uuid_is_typed(
        client, make_person, sign_in, unmatch_pair):
    """The route finds the person through ::uuid, which reads a uuid without
    hyphens or in capitals; the held rows name the person by its canonical
    text, so the statement must be bound with that, not the path as typed."""
    p = unmatch_pair
    voice = _hold_with_a_voice_note(client, p)
    admin = make_person(name='UnmatchAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=p.a['id'])).fetchone()['email']
    typed = p.a['uuid'].replace('-', '').upper()

    resp = client.delete(f'/admin/users/{typed}', headers=sign_in(admin),
                         json={'confirm_email': email, 'reason': 'test'})

    with api_tx() as tx:
        staged = _staged(tx, voice)
    assert resp.status_code == 200
    assert counts(p.a, p.b)['held'] == 0
    assert staged
