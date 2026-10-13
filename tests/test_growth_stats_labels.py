"""The Growth tab's figures measure what their labels say.

Three tiles on the Growth tab counted something other than their label until
the 13 Oct 2026 health review:

- "Acted 14 days", sub-labelled "Liked or messaged", also counted passes. It
  read 16 where 8 members had liked or messaged; the other 8 had only passed.
- "With photo" counted any photo row, so members whose only photos had been
  rejected (49, 113 and 117 in production) were counted as having one.
- "Messages 7 days" and "Messages 30 days" counted rows of `messaged`, which
  holds one row per sender and recipient, written on the FIRST message
  only. 30 days read 3 while 6 messages had been sent, and a pair that kept
  talking read 0 once its first message was older than the window.

Each test reads growth_stats() before and after one change and compares,
because the test database is shared and holds other tests' members.
"""
from __future__ import annotations

import uuid

from database import api_tx
from service.growth.queries import growth_stats


def _stats() -> dict:
    with api_tx('read committed') as tx:
        return growth_stats(tx)


def _woman(stats: dict) -> dict:
    return next((r for r in stats['members_by_gender'] if r['gender'] == 'Woman'),
                dict(acted_14d=0, with_photo=0, members=0))


_MAM_SEQ = [0]


def _message(sender_id: int, recipient_id: int, days_ago: int = 0) -> None:
    """Both archive copies, as the chat service writes them. No content."""
    _MAM_SEQ[0] += 1
    with api_tx() as tx:
        uuids = {r['id']: str(r['uuid']) for r in tx.execute(
            "SELECT id, uuid FROM person WHERE id IN (%(a)s, %(b)s)",
            dict(a=sender_id, b=recipient_id)).fetchall()}
        mam_id = tx.execute(
            """SELECT (EXTRACT(EPOCH FROM (NOW() - make_interval(days => %(d)s)))
                        * 1000000)::bigint * 256 + %(s)s AS id""",
            dict(d=days_ago, s=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'O', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id, pid=sender_id, jid=uuids[recipient_id]))
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'I', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id + 1, pid=recipient_id, jid=uuids[sender_id]))
        # What the chat service also does on a first message, so the old
        # first-contact count would see this too.
        tx.execute(
            """INSERT INTO messaged (subject_person_id, object_person_id, created_at)
               VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))
               ON CONFLICT DO NOTHING""",
            dict(a=sender_id, b=recipient_id, d=days_ago))


def _photo(person_id: int, position: int, status: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (person_id, position, uuid, blurhash, hash, moderation_status)
               VALUES (%(p)s, %(pos)s, %(u)s, '', %(u)s, %(st)s)""",
            dict(p=person_id, pos=position, u=f'growth-label-{uuid.uuid4().hex}', st=status))


# ---------------------------------------------------------------------------
# Acted 14 days: liked or messaged
# ---------------------------------------------------------------------------

def test_a_pass_alone_is_not_acting(make_person):
    passer = make_person(name='OnlyPasses', gender='Woman')
    other = make_person(name='Passed', gender='Man')
    before = _woman(_stats())['acted_14d']
    with api_tx() as tx:
        tx.execute(
            "INSERT INTO skipped (subject_person_id, object_person_id, created_at) VALUES (%(a)s, %(b)s, NOW())",
            dict(a=passer['id'], b=other['id']))
    assert _woman(_stats())['acted_14d'] == before, 'a pass counted as liked or messaged'

    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(a)s, %(b)s, NOW())",
                   dict(a=passer['id'], b=other['id']))
    assert _woman(_stats())['acted_14d'] == before + 1


def test_a_message_on_an_old_conversation_is_acting(make_person):
    """The first message was 40 days ago; the latest is today. `messaged`
    only ever saw the first, so this member read as having done nothing."""
    writer = make_person(name='StillWriting', gender='Woman')
    other = make_person(name='Reader', gender='Man')
    _message(writer['id'], other['id'], days_ago=40)
    before = _woman(_stats())['acted_14d']
    _message(writer['id'], other['id'], days_ago=0)
    assert _woman(_stats())['acted_14d'] == before + 1


def test_a_like_older_than_14_days_is_not_acting(make_person):
    liker = make_person(name='LikedLongAgo', gender='Woman')
    other = make_person(name='LongAgoLiked', gender='Man')
    before = _woman(_stats())['acted_14d']
    with api_tx() as tx:
        tx.execute(
            "INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(a)s, %(b)s, NOW() - interval '15 days')",
            dict(a=liker['id'], b=other['id']))
    assert _woman(_stats())['acted_14d'] == before


# ---------------------------------------------------------------------------
# With photo: an approved photo
# ---------------------------------------------------------------------------

def test_with_photo_counts_an_approved_photo_only(make_person):
    p = make_person(name='PhotoStates', gender='Woman')
    before = _woman(_stats())['with_photo']
    _photo(p['id'], 1, 'rejected')
    _photo(p['id'], 2, 'pending')
    assert _woman(_stats())['with_photo'] == before, 'a rejected or pending photo counted'
    _photo(p['id'], 3, 'approved')
    assert _woman(_stats())['with_photo'] == before + 1


# ---------------------------------------------------------------------------
# Messages: messages, not first contacts
# ---------------------------------------------------------------------------

def test_messages_count_every_message_sent(make_person):
    a = make_person(name='MsgCountA', gender='Woman')
    b = make_person(name='MsgCountB', gender='Man')
    before = _stats()
    _message(a['id'], b['id'])
    _message(b['id'], a['id'])
    _message(a['id'], b['id'])
    after = _stats()
    assert after['msgs_7d'] == before['msgs_7d'] + 3
    assert after['msgs_30d'] == before['msgs_30d'] + 3


def test_a_conversation_keeps_counting_after_its_first_message_ages_out(make_person):
    a = make_person(name='LongTalkA', gender='Woman')
    b = make_person(name='LongTalkB', gender='Man')
    _message(a['id'], b['id'], days_ago=40)
    before = _stats()
    _message(a['id'], b['id'], days_ago=2)
    after = _stats()
    assert after['msgs_7d'] == before['msgs_7d'] + 1
    assert after['msgs_30d'] == before['msgs_30d'] + 1


def test_growth_and_overview_count_messages_the_same_way(make_person):
    """One label, one measure: the Overview's "Messages 7d" reads the same
    rows. Growth also leaves out test addresses; these are not."""
    from service.admin.queries.engagement import Q_ENGAGEMENT_KPIS
    a = make_person(name='SameWayA', gender='Woman')
    b = make_person(name='SameWayB', gender='Man')

    def both():
        with api_tx('read committed') as tx:
            return growth_stats(tx)['msgs_7d'], tx.execute(Q_ENGAGEMENT_KPIS).fetchone()['messages_7d']

    g0, o0 = both()
    _message(a['id'], b['id'])
    _message(b['id'], a['id'])
    g1, o1 = both()
    assert g1 - g0 == o1 - o0 == 2
