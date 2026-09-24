"""Likes, matches and conversations.

The owner's constraint is explicit and is tested rather than trusted: chats
initiated and chats responded to, never content.

Each test here targets one of the four traps named in
`service/admin/queries/engagement.py`, because every one of them gives a
plausible wrong answer rather than an error.
"""
import hashlib
import secrets

import pytest

from database import api_tx
from service.admin.queries.engagement import Q_ENGAGEMENT_KPIS


def _kpis() -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_ENGAGEMENT_KPIS).fetchone())


def _like(liker_id: int, liked_id: int) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO liked (liker_id, liked_id, created_at)
               VALUES (%(a)s, %(b)s, NOW())
               ON CONFLICT DO NOTHING""",
            dict(a=liker_id, b=liked_id))


def _uuid_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return str(tx.execute("SELECT uuid FROM person WHERE id = %(i)s",
                              dict(i=person_id)).fetchone()['uuid'])


_MAM_SEQ = [0]


def _message(sender, recipient, *, days_ago: int = 0) -> None:
    """Write a message the way the chat service does: TWO rows, one in each
    participant's archive, with a MAM id encoding the time.

    Writing only one row would hide the double-count trap this suite exists
    to catch, so the helper mirrors production exactly.
    """
    _MAM_SEQ[0] += 1
    with api_tx() as tx:
        mam_id = tx.execute(
            """SELECT (EXTRACT(EPOCH FROM (NOW() - make_interval(days => %(d)s)))
                        * 1000000)::bigint * 256 + %(seq)s AS id""",
            dict(d=days_ago, seq=_MAM_SEQ[0] % 256)).fetchone()['id']
        # The outgoing copy sits in the sender's archive.
        tx.execute(
            """INSERT INTO mam_message
                 (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'O', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id, pid=sender['id'], jid=_uuid_of(recipient['id'])))
        # The incoming copy sits in the recipient's archive.
        tx.execute(
            """INSERT INTO mam_message
                 (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'I', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id + 1, pid=recipient['id'], jid=_uuid_of(sender['id'])))


# ---------------------------------------------------------------------------
# Likes and matches
# ---------------------------------------------------------------------------

def test_a_match_counts_once_not_twice(make_person):
    """Both directions of a mutual like are rows in `liked`. Without the
    liker_id < liked_id guard every match is counted twice, which is the
    kind of wrong answer that looks fine."""
    a, b = make_person(name='MatchA'), make_person(name='MatchB')
    before = _kpis()['matches_total']
    _like(a['id'], b['id'])
    _like(b['id'], a['id'])
    assert _kpis()['matches_total'] == before + 1


def test_a_one_way_like_is_not_a_match(make_person):
    """Negative control for the test above."""
    a, b = make_person(name='OneWayA'), make_person(name='OneWayB')
    before = _kpis()
    _like(a['id'], b['id'])
    after = _kpis()
    assert after['matches_total'] == before['matches_total']
    assert after['likes_total'] == before['likes_total'] + 1


# ---------------------------------------------------------------------------
# Conversations. The distinction the owner asked for.
# ---------------------------------------------------------------------------

def test_a_conversation_with_one_sender_is_initiated_but_not_answered(make_person):
    """Someone reached out and nobody replied. A pile of these looks
    identical to a busy community until the two numbers are split."""
    a, b = make_person(name='SpeakerA'), make_person(name='SilentB')
    before = _kpis()
    _message(a, b)
    after = _kpis()
    assert after['conversations_total'] == before['conversations_total'] + 1
    assert after['conversations_answered'] == before['conversations_answered']


def test_a_conversation_both_sides_have_written_in_counts_as_answered(make_person):
    a, b = make_person(name='ReplyA'), make_person(name='ReplyB')
    before = _kpis()
    _message(a, b)
    _message(b, a)
    after = _kpis()
    assert after['conversations_total'] == before['conversations_total'] + 1, \
        'a reply must not open a second conversation: {a,b} and {b,a} are one'
    assert after['conversations_answered'] == before['conversations_answered'] + 1


def test_more_messages_do_not_open_more_conversations(make_person):
    """Ten messages between two people are one conversation."""
    a, b = make_person(name='ChattyA'), make_person(name='ChattyB')
    before = _kpis()['conversations_total']
    for _ in range(5):
        _message(a, b)
        _message(b, a)
    assert _kpis()['conversations_total'] == before + 1


def test_messages_are_not_double_counted(make_person):
    """mam_message stores each message twice, once per participant. On
    2026-09-24 production held 58 rows for 29 messages, so a query that
    forgets the direction filter reports exactly double."""
    a, b = make_person(name='CountA'), make_person(name='CountB')
    before = _kpis()['messages_total']
    _message(a, b)
    _message(b, a)
    with api_tx('read committed') as tx:
        raw = tx.execute(
            """SELECT count(*) AS n FROM mam_message
                WHERE person_id IN (%(a)s, %(b)s)""",
            dict(a=a['id'], b=b['id'])).fetchone()['n']
    assert raw == 4, 'the helper must write both archive copies, like production does'
    assert _kpis()['messages_total'] == before + 2


def test_the_mam_id_decodes_to_a_real_time(make_person):
    """`mam_message` has no timestamp column; the id encodes one. Getting
    the decode subtly wrong would silently empty every windowed figure
    rather than raising."""
    a, b = make_person(name='WindowA'), make_person(name='WindowB')
    before = _kpis()
    _message(a, b, days_ago=0)
    _message(a, b, days_ago=30)
    after = _kpis()
    assert after['messages_total'] == before['messages_total'] + 2
    assert after['messages_7d'] == before['messages_7d'] + 1, \
        'the 30 day old message must fall outside the 7 day window'


# ---------------------------------------------------------------------------
# The standing prohibition
# ---------------------------------------------------------------------------

def test_no_engagement_query_touches_message_content():
    """The owner asked for counts, not content. This is a guard against a
    later edit widening that quietly, so it reads the module rather than
    relying on anyone remembering."""
    import service.admin.queries.engagement as eng
    with open(eng.__file__, encoding='utf-8') as fh:
        src = fh.read()
    # The docstring names these columns to explain why they are banned, so
    # check only the SQL constants themselves.
    sql = eng.Q_ENGAGEMENT_KPIS.lower()
    for forbidden in ('search_body', 'translations', 'm.message', 'audio_uuid'):
        assert forbidden not in sql, f'engagement SQL references {forbidden}'
    assert 'select' in sql
