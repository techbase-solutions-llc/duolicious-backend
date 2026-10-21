"""Members someone is waiting on, and the weekly funnel (TEC-1897).

CONTENT IS NEVER READ. Messages come from engagement._SENT_MESSAGES, which
reads mam_message's id, direction, person and other party only. No query
here may name `message`, `search_body`, `translations` or `audio_uuid`;
tests/test_admin_community_waiting.py and tests/test_admin_funnel.py read
the SQL and fail if one appears.

Never who liked whom: the lists here are per member counts. A row names
the member who is waiting to answer, never the people waiting on them.

Every figure is between counted members (members.counted_member_sql):
active ones for the lists of who is waiting now, any member for history.
Every query binds %(ex)s with service.growth.queries._excluded().
"""
from __future__ import annotations

from service.admin.queries.engagement import _SENT_MESSAGES
from service.admin.queries.members import counted_member_sql


def waiting_likes_sql() -> str:
    """Likes nobody has answered: `person_id` is the member who was liked
    and has neither liked back nor passed. A pass by the liker since then
    withdraws the like."""
    return f"""
        SELECT l.liked_id AS person_id, l.liker_id, l.created_at
          FROM liked l
          JOIN person a ON a.id = l.liker_id
          JOIN person b ON b.id = l.liked_id
         WHERE {counted_member_sql('a')} AND {counted_member_sql('b')}
           AND NOT EXISTS (SELECT 1 FROM liked r
                            WHERE r.liker_id = l.liked_id AND r.liked_id = l.liker_id)
           AND NOT EXISTS (SELECT 1 FROM skipped s
                            WHERE (s.subject_person_id = l.liked_id AND s.object_person_id = l.liker_id)
                               OR (s.subject_person_id = l.liker_id AND s.object_person_id = l.liked_id))
    """


def member_sent_sql(active: bool) -> str:
    """One row per message sent between counted members (sender_id,
    recipient_id, lo, hi, sent_at)."""
    return f"""
        SELECT x.sender_id, x.recipient_id, x.lo, x.hi, x.sent_at
          FROM ({_SENT_MESSAGES}) x
          JOIN person xs ON xs.id = x.sender_id
          JOIN person xr ON xr.id = x.recipient_id
         WHERE {counted_member_sql('xs', active=active)} AND {counted_member_sql('xr', active=active)}
    """


# One row per conversation: when it opened, who opened it, and how many
# people have written in it (2 means both sides did).
_CONVOS = """
        SELECT lo, hi, min(sent_at) AS opened_at,
               (array_agg(sender_id ORDER BY sent_at))[1] AS opener,
               count(DISTINCT sender_id) AS voices
          FROM sent GROUP BY lo, hi
"""

# Matches between active counted members that neither has blocked: a block
# hides the match from both (is_blocked_pair, migration 0035).
_MEMBER_MATCHES = f"""
        SELECT m.user_a_id, m.user_b_id, m.created_at
          FROM ahavah_match m
          JOIN person ma ON ma.id = m.user_a_id
          JOIN person mb ON mb.id = m.user_b_id
         WHERE {counted_member_sql('ma')} AND {counted_member_sql('mb')}
           AND NOT is_blocked_pair(m.user_a_id, m.user_b_id)
"""

_SILENT = """
        SELECT mm.user_a_id, mm.user_b_id, mm.created_at
          FROM member_matches mm
         WHERE mm.created_at < NOW() - INTERVAL '7 days'
           AND NOT EXISTS (SELECT 1 FROM sent x WHERE x.lo = mm.user_a_id AND x.hi = mm.user_b_id)
"""

_WITH = f"""
    WITH sent AS ({member_sent_sql(active=True)}),
    likes AS ({waiting_likes_sql()}),
    convos AS (SELECT c.* FROM ({_CONVOS}) c WHERE NOT is_blocked_pair(c.lo, c.hi)),
    member_matches AS ({_MEMBER_MATCHES}),
    silent AS ({_SILENT}),
    per AS (SELECT person_id, count(*) AS n, min(created_at) AS oldest
              FROM likes GROUP BY person_id)
"""

Q_WAITING_SUMMARY = f"""
    {_WITH}
    SELECT
      (SELECT count(*) FROM likes)::int                                   AS likes_waiting,
      (SELECT count(*) FROM per)::int                                     AS members_with_likes,
      (SELECT min(oldest) FROM per)                                       AS oldest_like_at,
      (SELECT count(*) FROM per JOIN person p ON p.id = per.person_id
        WHERE p.last_online_time < NOW() - INTERVAL '7 days')::int        AS offline_7d,
      (SELECT count(*) FROM per WHERE EXISTS (
          SELECT 1 FROM push_subscription ps WHERE ps.person_id = per.person_id))::int AS push_on,
      (SELECT count(*) FROM per WHERE n >= 5)::int                        AS with_5_or_more,
      (SELECT count(*) FROM per WHERE n BETWEEN 2 AND 4)::int             AS with_2_to_4,
      (SELECT count(*) FROM per WHERE n = 1)::int                         AS with_1,
      (SELECT count(*) FROM convos)::int                                  AS conversations,
      (SELECT count(*) FROM convos WHERE voices = 1)::int                 AS one_sided,
      (SELECT min(opened_at) FROM convos WHERE voices = 1)                AS oldest_unanswered_at,
      (SELECT count(*) FROM member_matches)::int                          AS matches,
      (SELECT count(*) FROM silent)::int                                  AS silent_matches_7d
"""

Q_WAITING_MEMBERS = f"""
    {_WITH},
    waits AS (
        SELECT person_id, created_at AS since, 'like' AS kind FROM likes
        UNION ALL
        SELECT CASE WHEN opener = lo THEN hi ELSE lo END, opened_at, 'opener'
          FROM convos WHERE voices = 1
        UNION ALL
        SELECT user_a_id, created_at, 'match' FROM silent
        UNION ALL
        SELECT user_b_id, created_at, 'match' FROM silent
    )
    SELECT p.uuid::text AS uuid, p.name,
           count(*) FILTER (WHERE w.kind = 'like')::int   AS likes_waiting,
           count(*) FILTER (WHERE w.kind = 'opener')::int AS unanswered_openers,
           count(*) FILTER (WHERE w.kind = 'match')::int  AS silent_matches,
           min(w.since)                                   AS oldest_wait_at,
           p.last_online_time                             AS last_online_at,
           EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id) AS push_on
      FROM waits w
      JOIN person p ON p.id = w.person_id
     GROUP BY p.id
     ORDER BY min(w.since), p.id
     LIMIT 200
"""
