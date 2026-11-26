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

from service.admin.queries.engagement import member_sent_sql
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


# One row per conversation: when it opened, who opened it, and how many
# people have written in it (2 means both sides did).
_CONVOS = """
        SELECT lo, hi, min(sent_at) AS opened_at,
               (array_agg(sender_id ORDER BY sent_at))[1] AS opener,
               count(DISTINCT sender_id) AS voices
          FROM sent GROUP BY lo, hi
"""

# Matches between active counted members that neither has blocked: a block
# hides the match from both (is_blocked_pair, migration 0035). The summary's
# `matches` is "Matches now" in the admin: current matches only, not the
# Overview's and Growth's "Matches made", every match ever made (TEC-2150).
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
              FROM likes GROUP BY person_id),
    -- Every reason a member is waited on: a like, an opener they have not
    -- answered, a match where nobody has written. The list below is one row
    -- per member in here, and members_waiting counts them, so the Needs you
    -- tile and the list it opens agree. The tile counted members with likes
    -- only, 29 against a list of 32 on 11 Nov 2026 (TEC-2150).
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
"""

Q_WAITING_SUMMARY = f"""
    {_WITH}
    SELECT
      (SELECT count(DISTINCT person_id) FROM waits)::int                  AS members_waiting,
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

# Write to them (TEC-2210): one note to a member in this many days. The
# latest waiting_note row (migration 0102) starts the window.
NOTE_WINDOW_DAYS = 7

# The latest note to the member `p` and the time from which another is
# allowed, NULL when one is allowed now.
_NOTE_SENT_AT = "(SELECT max(wn.sent_at) FROM waiting_note wn WHERE wn.person_id = p.id)"
_CAN_NOTE_AT = f"""(SELECT CASE WHEN max(wn.sent_at) > NOW() - INTERVAL '{NOTE_WINDOW_DAYS} days'
                        THEN max(wn.sent_at) + INTERVAL '{NOTE_WINDOW_DAYS} days' END
                     FROM waiting_note wn WHERE wn.person_id = p.id)"""

Q_WAITING_MEMBERS = f"""
    {_WITH}
    SELECT p.uuid::text AS uuid, p.name,
           count(*) FILTER (WHERE w.kind = 'like')::int   AS likes_waiting,
           count(*) FILTER (WHERE w.kind = 'opener')::int AS unanswered_openers,
           count(*) FILTER (WHERE w.kind = 'match')::int  AS silent_matches,
           min(w.since)                                   AS oldest_wait_at,
           p.last_online_time                             AS last_online_at,
           EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id) AS push_on,
           {_NOTE_SENT_AT}                                AS note_sent_at,
           {_CAN_NOTE_AT}                                 AS can_note_at
      FROM waits w
      JOIN person p ON p.id = w.person_id
     GROUP BY p.id
     ORDER BY min(w.since), p.id
     LIMIT 200
"""

# Is anybody waiting on the member %(pid)s now: the list's own rule, so a
# member the list shows can be written to and nobody else.
Q_IS_WAITING = f"""
    {_WITH}
    SELECT EXISTS (SELECT 1 FROM waits WHERE person_id = %(pid)s) AS waiting
"""


from service.admin.queries.days import BARBADOS_TODAY  # noqa: E402


def _week(col: str) -> str:
    """The Monday of the Barbados week a timestamptz falls in."""
    return f"date_trunc('week', ({col} AT TIME ZONE 'America/Barbados'))::date"


Q_WEEKLY_FUNNEL = f"""
    WITH weeks AS (
        SELECT generate_series(
                 date_trunc('week', ({BARBADOS_TODAY})::timestamp) - INTERVAL '11 weeks',
                 date_trunc('week', ({BARBADOS_TODAY})::timestamp),
                 INTERVAL '1 week')::date AS wk
    ),
    likes AS (
        SELECT {_week('l.created_at')} AS wk
          FROM liked l
          JOIN person a ON a.id = l.liker_id
          JOIN person b ON b.id = l.liked_id
         WHERE {counted_member_sql('a', active=False)} AND {counted_member_sql('b', active=False)}
    ),
    matches AS (
        SELECT {_week('m.created_at')} AS wk
          FROM ahavah_match m
          JOIN person ma ON ma.id = m.user_a_id
          JOIN person mb ON mb.id = m.user_b_id
         WHERE {counted_member_sql('ma', active=False)} AND {counted_member_sql('mb', active=False)}
    ),
    sent AS ({member_sent_sql(active=False)}),
    convos AS ({_CONVOS}),
    replies AS (
        SELECT c.lo, c.hi, min(x.sent_at) AS replied_at
          FROM convos c
          JOIN sent x ON x.lo = c.lo AND x.hi = c.hi AND x.sender_id <> c.opener
         GROUP BY c.lo, c.hi
    )
    SELECT w.wk AS week_start,
           (SELECT count(*) FROM likes x WHERE x.wk = w.wk)::int                      AS likes,
           (SELECT count(*) FROM matches x WHERE x.wk = w.wk)::int                    AS matches,
           (SELECT count(*) FROM convos c WHERE {_week('c.opened_at')} = w.wk)::int   AS first_messages,
           (SELECT count(*) FROM replies r WHERE {_week('r.replied_at')} = w.wk)::int AS replies
      FROM weeks w
     ORDER BY w.wk
"""
