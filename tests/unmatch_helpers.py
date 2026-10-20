"""Set-up the unmatch tests share (TEC-1845, migration 0070): a matched pair
and a conversation stored the way the app stores them, and a count of what
is left of it."""
from __future__ import annotations

import itertools
import time

from database import api_tx

# The chat server's LSERVER default (service/chat/chatutil). The inbox stores
# the other person as uuid@domain; the archive stores the bare uuid.
DOMAIN = 'ahavah.app'
_seq = itertools.count()


def match(a: dict, b: dict) -> str:
    """Both likes and the match row, as /decisions leaves them."""
    with api_tx() as tx:
        for liker, liked in ((a, b), (b, a)):
            tx.execute(
                "INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s) ON CONFLICT DO NOTHING",
                dict(a=liker['id'], b=liked['id']))
        return tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id)
               VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))
               RETURNING match_id::text AS match_id""",
            dict(a=a['id'], b=b['id'])).fetchone()['match_id']


def converse(sender: dict, recipient: dict, body: str = 'Shalom',
             audio_uuid: str | None = None) -> int:
    """One message as service/chat/messagestorage stores it: a copy in each
    archive ('O' for the sender, 'I' for the recipient), both inbox rows and
    the sender's messaged row. Returns the sender's archive id."""
    mid = ((time.time_ns() // 1000) << 8) + 2 * next(_seq)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO mam_message (id, from_jid, remote_bare_jid, direction, message,
                                        search_body, audio_uuid, person_id)
               VALUES (%(id)s, '', %(to)s, 'O', %(m)s, %(b)s, %(au)s, %(sid)s),
                      (%(id)s + 1, '', %(frm)s, 'I', %(m)s, %(b)s, %(au)s, %(rid)s)""",
            dict(id=mid, to=recipient['uuid'], frm=sender['uuid'], m=body.encode(),
                 b=body.lower(), au=audio_uuid, sid=sender['id'], rid=recipient['id']))
        for luser, remote, unread in ((sender, recipient, 0), (recipient, sender, 1)):
            tx.execute(
                """INSERT INTO inbox (luser, remote_bare_jid, msg_id, box, content, timestamp,
                                      unread_count)
                   VALUES (%(l)s, %(r)s, %(mid)s, 'chats', %(c)s, %(ts)s, %(n)s)
                   ON CONFLICT (luser, remote_bare_jid) DO UPDATE
                      SET unread_count = EXCLUDED.unread_count""",
                dict(l=luser['uuid'], r=f"{remote['uuid']}@{DOMAIN}", mid=str(mid),
                     c=b'<message/>', ts=mid >> 8, n=unread))
        tx.execute(
            """INSERT INTO messaged (subject_person_id, object_person_id)
               VALUES (%(s)s, %(o)s) ON CONFLICT DO NOTHING""",
            dict(s=sender['id'], o=recipient['id']))
    return mid


def counts(a: dict, b: dict) -> dict:
    """What is left of this pair's match and conversation, where each is kept."""
    with api_tx('read committed') as tx:
        return dict(tx.execute(
            """SELECT
                 (SELECT count(*) FROM mam_message
                   WHERE (person_id = %(a)s AND split_part(remote_bare_jid, '@', 1) = %(bu)s)
                      OR (person_id = %(b)s AND split_part(remote_bare_jid, '@', 1) = %(au)s)) AS archive,
                 (SELECT count(*) FROM unmatched_message
                   WHERE (person_id = %(a)s AND split_part(remote_bare_jid, '@', 1) = %(bu)s)
                      OR (person_id = %(b)s AND split_part(remote_bare_jid, '@', 1) = %(au)s)) AS held,
                 (SELECT count(*) FROM inbox
                   WHERE (luser = %(au)s AND split_part(remote_bare_jid, '@', 1) = %(bu)s)
                      OR (luser = %(bu)s AND split_part(remote_bare_jid, '@', 1) = %(au)s)) AS inbox,
                 (SELECT count(*) FROM messaged
                   WHERE (subject_person_id = %(a)s AND object_person_id = %(b)s)
                      OR (subject_person_id = %(b)s AND object_person_id = %(a)s)) AS messaged,
                 (SELECT count(*) FROM ahavah_match
                   WHERE user_a_id = LEAST(%(a)s, %(b)s)
                     AND user_b_id = GREATEST(%(a)s, %(b)s)) AS matches""",
            dict(a=a['id'], b=b['id'], au=a['uuid'], bu=b['uuid'])).fetchone())
