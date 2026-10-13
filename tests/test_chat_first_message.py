"""A matched member's hello is never refused by the intro filters
(health review, 13 Oct 2026, finding 41).

Chat is open to matched pairs only (service/chat, operator ruling
2026-07-21), yet every message to a peer who has not written back still
counted as a Duolicious "intro": it had to be unique across ALL members for
7 days (robot9000) and fell under the unverified 10 a day intro cap. Two
members opening with the same "Shalom" in the same week, or one member
greeting a busy day's matches, would be refused with a reason that made no
sense to them.

A matched pair now skips both. The match gate already stops cold contact,
and the two filters stay in place for an unmatched first message should
intros ever come back. These tests go through `process_text`, the
websocket handler, with only the Redis publish and the message store
replaced.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import duohash
import pytest

import service.chat as chat
from database import api_tx
from service.chat.chatutil import LSERVER
from service.chat.message import ChatMessage
from service.chat.xmlparse import parse_xml_or_none


@pytest.fixture
def pair(make_person):
    sender = make_person(name='Sender', gender='Man')
    recipient = make_person(name='Recipient', gender='Woman')
    yield sender, recipient
    with api_tx() as tx:
        tx.execute("DELETE FROM intro_hash WHERE hash = ANY(%(h)s)", dict(h=_hashes))
    _hashes.clear()


_hashes: list[str] = []


def _match(a: dict, b: dict) -> None:
    with api_tx() as tx:
        tx.execute(
            "INSERT INTO ahavah_match (user_a_id, user_b_id) "
            "VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))",
            dict(a=a['id'], b=b['id']))


def _used_this_week(body: str) -> None:
    """Someone else sent these words as an opener in the last 7 days."""
    h = duohash.md5(chat.normalize_message(body))
    _hashes.append(h)
    with api_tx() as tx:
        tx.execute(
            "INSERT INTO intro_hash (hash, last_used_at) VALUES (%(h)s, now() - interval '2 days') "
            "ON CONFLICT (hash) DO UPDATE SET last_used_at = EXCLUDED.last_used_at",
            dict(h=h))


def _past_the_intro_cap(person: dict) -> None:
    """8 rude messages in a day halve the 10 a day cap 4 times, to 0, so
    any intro is refused (service/chat/ratelimit)."""
    with api_tx() as tx:
        for i in range(8):
            tx.execute(
                "INSERT INTO rude_message (person_id, created_at, message) "
                "VALUES (%(p)s, NOW() - make_interval(mins => %(i)s), 'x')",
                dict(p=person['id'], i=i + 1))


def _send(monkeypatch, sender: dict, recipient: dict, body: str) -> tuple[list[str], list[dict]]:
    """Run one chat message through process_text. Returns what was
    published back and what was handed to the message store."""
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


def test_a_matched_hello_is_sent_when_someone_else_used_the_same_words(monkeypatch, pair):
    sender, recipient = pair
    _match(sender, recipient)
    body = f'Shalom {uuid4().hex}'
    _used_this_week(body)

    published, stored = _send(monkeypatch, sender, recipient, body)

    assert not any('duo_message_not_unique' in m for m in published), published
    assert len(stored) == 1


def test_a_matched_hello_is_sent_past_the_intro_cap(monkeypatch, pair):
    sender, recipient = pair
    _match(sender, recipient)
    _past_the_intro_cap(sender)

    published, stored = _send(monkeypatch, sender, recipient, f'Shalom {uuid4().hex}')

    assert not any('rate-limited' in m for m in published), published
    assert len(stored) == 1


def test_an_unmatched_message_is_still_refused_as_not_matched(monkeypatch, pair):
    sender, recipient = pair

    published, stored = _send(monkeypatch, sender, recipient, f'Shalom {uuid4().hex}')

    assert len(published) == 1 and 'reason="not-matched"' in published[0]
    assert stored == []


def test_the_intro_filters_still_apply_to_an_unmatched_first_message(pair, make_person):
    """Unreachable today (the match gate refuses first), kept for the day
    intros return: the filters and their failure reasons are unchanged."""
    sender, _ = pair
    # The cap is read once and cached for a few seconds per sender, so the
    # capped case gets a sender of its own.
    capped_sender = make_person(name='CappedSender', gender='Man')
    repeated = ChatMessage(stanza_id=uuid4().hex, to_username='x', body=f'Shalom {uuid4().hex}')
    _used_this_week(repeated.body)
    fresh = ChatMessage(stanza_id=uuid4().hex, to_username='x', body=f'Shalom {uuid4().hex}')

    async def refusals():
        return (
            await chat.first_message_refusal(
                from_id=sender['id'], message=repeated, is_intro=True, is_matched=False),
            await chat.first_message_refusal(
                from_id=sender['id'], message=repeated, is_intro=True, is_matched=True),
            await chat.first_message_refusal(
                from_id=sender['id'], message=repeated, is_intro=False, is_matched=False),
        )

    not_unique, matched, reply = asyncio.run(refusals())
    assert not_unique == [f'<duo_message_not_unique id="{repeated.stanza_id}"/>']
    assert matched == [] and reply == []

    _past_the_intro_cap(capped_sender)
    capped = asyncio.run(chat.first_message_refusal(
        from_id=capped_sender['id'], message=fresh, is_intro=True, is_matched=False))
    assert len(capped) == 1 and 'reason="rate-limited-1day"' in capped[0]
