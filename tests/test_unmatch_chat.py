"""Unmatch in the chat server (TEC-1845, migration 0070). After an unmatch
neither person can write, see the other online or load the old history,
and a message that slipped past the gate's 5 second cache is never stored.
process_text runs as in tests/test_chat_first_message.py, with only the
Redis publish and the message store replaced."""
from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest

import service.chat as chat
from database import api_tx
from service.chat.chatutil import LSERVER, fetch_is_skipped
from service.chat.messagestorage import StoreMessageJob, _process_store_message_batch
from service.chat.messagestorage.inbox import UpsertConversationJob
from service.chat.messagestorage.mam import Q_SELECT_MESSAGE, StoreMamMessageJob
from service.chat.messagestorage.setmessaged import SetMessagedJob
from service.chat.xmlparse import parse_xml_or_none
from tests.unmatch_helpers import converse, counts, match

pytestmark = pytest.mark.usefixtures('no_limits')


def _unmatch(client, p) -> None:
    assert client.post(f'/unmatch/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200


def _send(monkeypatch, sender: dict, recipient: dict, body: str) -> tuple[list[str], list[dict]]:
    published: list[str] = []
    stored: list[dict] = []

    async def publish(channel, messages):
        published.extend(messages)

    monkeypatch.setattr(chat, 'redis_publish_many', publish)
    monkeypatch.setattr(chat, 'store_message', lambda **kw: stored.append(kw))
    session = chat.Session()
    session.username = sender['uuid']
    xml = (f'<message xmlns="jabber:client" type="chat" id="{uuid4().hex}" '
           f'to="{recipient["uuid"]}@{LSERVER}"><body>{body}</body></message>')
    asyncio.run(chat.process_text(session, parse_xml_or_none, None, xml))
    return published, stored


def _job(sender: dict, recipient: dict, body: str, at_us: int,
         audio_uuid: str | None = None) -> StoreMessageJob:
    """What service/chat/messagestorage.store_message enqueues for one message."""
    msg_id = uuid4().hex
    return StoreMessageJob(
        store_mam_message_job=StoreMamMessageJob(
            timestamp_microseconds=at_us, from_username=sender['uuid'],
            to_username=recipient['uuid'], id=msg_id, message_body=body, audio_uuid=audio_uuid),
        upsert_conversation_job=UpsertConversationJob(
            from_username=sender['uuid'], to_username=recipient['uuid'], msg_id=msg_id,
            content=b'<message/>'),
        messaged_job=SetMessagedJob(from_id=sender['id'], to_id=recipient['id']))


def test_neither_can_write_after_an_unmatch(client, monkeypatch, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    converse(p.a, p.b)
    _unmatch(client, p)

    for sender, recipient in ((p.a, p.b), (p.b, p.a)):
        published, stored = _send(monkeypatch, sender, recipient, f'Still there {uuid4().hex}')
        assert any('duo_message_blocked' in m and 'not-matched' in m for m in published), published
        assert stored == []


def test_neither_sees_the_other_online(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)
    assert asyncio.run(fetch_is_skipped(from_id=p.a['id'], to_id=p.b['id']))
    assert asyncio.run(fetch_is_skipped(from_id=p.b['id'], to_id=p.a['id']))


def test_the_history_is_empty_for_both(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    converse(p.a, p.b, 'Shalom')
    converse(p.b, p.a, 'Shalom to you')
    _unmatch(client, p)
    with api_tx('read committed') as tx:
        for me, other in ((p.a, p.b), (p.b, p.a)):
            rows = tx.execute(Q_SELECT_MESSAGE, dict(
                from_username=me['uuid'], to_username=other['uuid'], before_id=None, max=None)).fetchall()
            assert rows == []


def test_a_message_that_passed_the_gate_is_never_stored(client, unmatch_pair, make_person):
    p = unmatch_pair
    control = make_person(name='Control', gender='Woman')
    match(p.a, p.b)
    match(p.b, control)
    _unmatch(client, p)
    now_us = time.time_ns() // 1000
    try:
        _process_store_message_batch([
            _job(p.b, p.a, 'Still there?', now_us),
            _job(p.b, control, 'Shalom', now_us + 1),
        ])
        assert counts(p.a, p.b) == dict(archive=0, held=0, inbox=0, messaged=0, matches=0)
        kept = counts(p.b, control)
        assert (kept['archive'], kept['inbox'], kept['messaged']) == (2, 2, 1)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM inbox WHERE luser = %(c)s', dict(c=control['uuid']))


def test_a_message_racing_the_unmatch_waits_for_it(client, unmatch_pair):
    """The unmatch holds both people in the like order while it commits. A
    store batch flushed in that moment must wait for it and then drop the
    message, or it reads no pair record and writes the conversation back
    after the unmatch has moved it out."""
    import threading

    import psycopg

    import database

    p = unmatch_pair
    match(p.a, p.b)
    other = psycopg.connect(database._api_conninfo)
    other.execute('SELECT id FROM person WHERE id IN (%s, %s) ORDER BY id FOR UPDATE',
                  (p.a['id'], p.b['id']))
    other.execute("""INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by)
                     VALUES (LEAST(%s, %s), GREATEST(%s, %s), %s)""",
                  (p.a['id'], p.b['id'], p.a['id'], p.b['id'], p.a['id']))
    other.execute('DELETE FROM ahavah_match WHERE user_a_id = LEAST(%s, %s) AND user_b_id = GREATEST(%s, %s)',
                  (p.a['id'], p.b['id'], p.a['id'], p.b['id']))

    def commit_soon():
        time.sleep(1)
        other.commit()
        other.close()

    t = threading.Thread(target=commit_soon)
    t.start()
    try:
        _process_store_message_batch([_job(p.b, p.a, 'Still there?', time.time_ns() // 1000)])
    finally:
        t.join()

    assert counts(p.a, p.b) == dict(archive=0, held=0, inbox=0, messaged=0, matches=0)


def test_a_voice_note_that_passed_the_gate_goes_to_the_cleaner(client, unmatch_pair, make_person):
    """The store callback still uploads the voice note of a dropped message
    (its live delivery, decision 8), and nothing would ever name that file
    again. It goes to the CDN cleaner's queue, as the unmatch sends the held
    ones; a kept voice note does not."""
    p = unmatch_pair
    control = make_person(name='Control', gender='Woman')
    match(p.a, p.b)
    match(p.b, control)
    _unmatch(client, p)
    dropped, kept = uuid4().hex, uuid4().hex
    now_us = time.time_ns() // 1000
    try:
        _process_store_message_batch([
            _job(p.b, p.a, '', now_us, audio_uuid=dropped),
            _job(p.b, control, '', now_us + 1, audio_uuid=kept),
        ])
        with api_tx('read committed') as tx:
            queued = {r['uuid'] for r in tx.execute(
                'SELECT uuid FROM undeleted_audio WHERE uuid = ANY(%(u)s)',
                dict(u=[dropped, kept])).fetchall()}
        assert queued == {dropped}
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM undeleted_audio WHERE uuid = ANY(%(u)s)', dict(u=[dropped, kept]))
            tx.execute('DELETE FROM inbox WHERE luser = %(c)s', dict(c=control['uuid']))
