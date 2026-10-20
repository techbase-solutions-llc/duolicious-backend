"""Unmatch (TEC-1845; ahavah-web Claude Design/handoff/copy/
15-together-follow-ups.md, section 6).

6.2 promises: "The match and your conversation are removed for both of you,
and you will not see each other in Discover." One transaction, both people
locked in the like order (service/decisions/locking.py), so a like or a
super-like racing it either lands first and is undone here, or waits and
then meets the pair record:

  - unmatched_pair records the pair for good (migration 0070).
    is_blocked_pair covers it, so every surface a report hides the pair
    from hides an unmatched pair too, both ways; is_deck_suppressed covers
    it for Discover.
  - the ahavah_match row goes (match_question cascades), so the chat's
    match gate and every match reader stop at once.
  - both archives' copies of the conversation move from mam_message to
    unmatched_message: out of chat history, the inbox and the data export,
    held HOLD_DAYS for a report (antiabuse/sql Q_LAST_MESSAGES), then
    deleted by purge_held_messages (the daily leadretention cron).
  - both inbox rows, both messaged rows, the pair's reactions and their
    deck cache go, and a match email still queued for this match is skipped.

The likes stay. They are what happened and they keep the engagement figures
true; with unmatched_pair they cannot make a match again (Q_RECORD_LIKE and
the super-like refuse an unmatched pair).

Repeating it from either side answers as a success: the web's Try again
after a lost response must not read as a failure. Nobody is notified.
"""
from __future__ import annotations

from typing import Union

import duotypes as t
from database import api_tx
from service.decisions.locking import lock_like_members

HOLD_DAYS = 30

_Q_PAIR = """
    SELECT peer.id AS peer_id, peer.uuid::text AS peer_uuid, me.uuid::text AS me_uuid,
           m.match_id::text AS match_id, m.created_at AS matched_at,
           is_unmatched_pair(me.id, peer.id) AS unmatched
      FROM person me
      JOIN person peer
        ON peer.uuid = uuid_or_null(%(peer_uuid)s::text)
       AND peer.id <> me.id
      LEFT JOIN ahavah_match m
        ON m.user_a_id = LEAST(me.id, peer.id)
       AND m.user_b_id = GREATEST(me.id, peer.id)
     WHERE me.id = %(me)s
"""

_Q_RECORD = """
    INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by, matched_at)
    VALUES (LEAST(%(me)s, %(peer)s), GREATEST(%(me)s, %(peer)s), %(me)s, %(matched_at)s)
    ON CONFLICT (user_a_id, user_b_id) DO NOTHING
"""

_Q_END_MATCH = """
    DELETE FROM ahavah_match WHERE match_id = %(match_id)s::uuid
"""

# The archive stores the other person as a bare uuid and the inbox as
# uuid@domain; split_part reads both.
_Q_HOLD_MESSAGES = """
    WITH moved AS (
        DELETE FROM mam_message m
         WHERE (m.person_id = %(me)s   AND split_part(m.remote_bare_jid, '@', 1) = %(peer_uuid)s)
            OR (m.person_id = %(peer)s AND split_part(m.remote_bare_jid, '@', 1) = %(me_uuid)s)
        RETURNING m.person_id, m.id, m.remote_bare_jid, m.direction, m.message,
                  m.search_body, m.audio_uuid
    )
    INSERT INTO unmatched_message (person_id, id, remote_bare_jid, direction, message,
                                   search_body, audio_uuid, held_until)
    SELECT person_id, id, remote_bare_jid, direction, message, search_body, audio_uuid,
           NOW() + make_interval(days => %(days)s)
      FROM moved
    ON CONFLICT (person_id, id) DO NOTHING
"""

_Q_FORGET_INBOX = """
    DELETE FROM inbox
     WHERE (luser = %(me_uuid)s   AND split_part(remote_bare_jid, '@', 1) = %(peer_uuid)s)
        OR (luser = %(peer_uuid)s AND split_part(remote_bare_jid, '@', 1) = %(me_uuid)s)
"""

_Q_FORGET_MESSAGED = """
    DELETE FROM messaged
     WHERE (subject_person_id = %(me)s   AND object_person_id = %(peer)s)
        OR (subject_person_id = %(peer)s AND object_person_id = %(me)s)
"""

_Q_FORGET_REACTIONS = """
    DELETE FROM message_reactions
     WHERE (reactor_id = %(me)s   AND peer_id = %(peer)s)
        OR (reactor_id = %(peer)s AND peer_id = %(me)s)
"""

_Q_FORGET_DECK = """
    DELETE FROM search_cache
     WHERE (searcher_person_id = %(me)s   AND prospect_person_id = %(peer)s)
        OR (searcher_person_id = %(peer)s AND prospect_person_id = %(me)s)
"""

# The "It's a match!" email is queued under match-<match id>
# (service/decisions post_decisions). Queued only: one already reserved is
# on its way.
_Q_SKIP_MATCH_EMAIL = """
    UPDATE email_outbox SET state = 'skipped', last_error = 'unmatched'
     WHERE campaign = 'match' AND campaign_id = 'match-' || %(match_id)s
       AND state = 'queued'
"""

_STATEMENTS = (_Q_RECORD, _Q_END_MATCH, _Q_HOLD_MESSAGES, _Q_FORGET_INBOX,
               _Q_FORGET_MESSAGED, _Q_FORGET_REACTIONS, _Q_FORGET_DECK, _Q_SKIP_MATCH_EMAIL)

_Q_UNMATCHED = """
    SELECT p.uuid::text AS uuid
      FROM unmatched_pair u
      JOIN person p
        ON p.id = CASE WHEN u.user_a_id = %(me)s THEN u.user_b_id ELSE u.user_a_id END
     WHERE u.user_a_id = %(me)s OR u.user_b_id = %(me)s
     ORDER BY u.unmatched_at DESC
"""

# A voice note is one file both copies name. It goes to the CDN cleaner's
# queue unless a live message still names it.
_Q_PURGE_HELD = """
    WITH gone AS (
        DELETE FROM unmatched_message
         WHERE held_until < NOW()
        RETURNING audio_uuid
    ), staged AS (
        INSERT INTO undeleted_audio (uuid)
        SELECT DISTINCT g.audio_uuid
          FROM gone g
         WHERE g.audio_uuid IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM mam_message m WHERE m.audio_uuid = g.audio_uuid)
        ON CONFLICT DO NOTHING
    )
    SELECT 1 FROM gone
"""


def unmatch(s: t.SessionInfo, prospect_uuid: str) -> Union[dict, tuple]:
    if s.person_id is None:
        return 'Not signed in', 401

    with api_tx('READ COMMITTED') as tx:
        lock_like_members(tx, s.person_id, prospect_uuid)
        pair = tx.execute(_Q_PAIR, dict(me=s.person_id, peer_uuid=prospect_uuid)).fetchone()
        if pair is None or (pair['match_id'] is None and not pair['unmatched']):
            return {'error': 'not_matched'}, 404
        if pair['match_id'] is None:
            return {'ok': True}
        params = dict(
            me=s.person_id, peer=pair['peer_id'],
            me_uuid=pair['me_uuid'], peer_uuid=pair['peer_uuid'],
            match_id=pair['match_id'], matched_at=pair['matched_at'],
            days=HOLD_DAYS,
        )
        for statement in _STATEMENTS:
            tx.execute(statement, params)

    return {'ok': True}


def unmatched_people(s: t.SessionInfo) -> dict:
    """Everyone the caller is unmatched from, whoever unmatched. The web drops
    those conversations from the device's own cache (src/lib/unmatch.ts)."""
    with api_tx('READ COMMITTED') as tx:
        rows = tx.execute(_Q_UNMATCHED, dict(me=s.person_id)).fetchall()
    return {'uuids': [r['uuid'] for r in rows]}


def purge_held_messages(tx) -> int:
    """Delete every held message whose hold has ended. Daily, from
    service/cron/leadretention. Returns how many rows went."""
    return tx.execute(_Q_PURGE_HELD).rowcount
