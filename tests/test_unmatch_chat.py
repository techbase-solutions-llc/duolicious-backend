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


def _job(sender: dict, recipient: dict, body: str, at_us: int) -> StoreMessageJob:
    """What service/chat/messagestorage.store_message enqueues for one message."""
    msg_id = uuid4().hex
    return StoreMessageJob(
        store_mam_message_job=StoreMamMessageJob(
            timestamp_microseconds=at_us, from_username=sender['uuid'],
            to_username=recipient['uuid'], id=msg_id, message_body=body, audio_uuid=None),
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
