"""SQL for GET /admin/users/<uuid>/activity: one member's timeline and a
7 and 30 day summary (TEC-2092, ahavah-web docs/plans/
2026-11-04-member-activity.md).

The owner asked on 4 Nov 2026 to see what each member does and how they
interact. His answers: name the other member for likes, passes, views and
reports; never show message text.

MESSAGE TEXT IS NEVER READ. The chat archive (`mam_message`, and
`unmatched_message` for a conversation held after an unmatch) is read for
its id, owner, other party and direction only: a count and the last time.
`tests/test_admin_member_activity.py` reads every SQL string this module
builds and fails if the body, search or audio columns of the archive, a
report's reason or a feedback message appear in one.

How each source is read, and what it cannot tell:

- `liked`: one row per like, both directions. `is_super` marks a super like.
- `skipped`: a pass, one row per pair. A re-pass moves `created_at`, so only
  the latest pass of each pair is known. A row with `reported` is a report,
  and `person_report` (0072) keeps every report, so reports come from there.
- `swipe` (0001) is never written by the API: likes go to `liked` and
  passes to `skipped`. It is not read.
- `ahavah_match` holds live matches only; an unmatch deletes the row and
  `unmatched_pair.matched_at` keeps when the match was made, so a match is
  read from both.
- `messaged`: the first message from one member to another.
- `visited`: the LATEST view of each pair only, so repeat views are not
  counted. 0079 removed, and the API no longer writes, a view that is not
  between a man and a woman or that a staff account made.
- `verification_job` keeps no creation time and its rows go at
  `expires_at`, three days after they are made; a new check also deletes
  the member's earlier rows. So a photo check is known for three days, at
  `expires_at - 3 days`. An ID check that passed is `person.id_verified_at`;
  one that did not is the last status Stripe sent (0054).
- A member's own deactivation keeps no time. An admin's does
  (`admin_deactivated_at`), and so does a request to delete the account.
- `person.sign_up_time` is written when onboarding finishes: the person row
  is made then. When the member started signing up is not kept (the
  `onboardee` row goes at finish), so "Joined" is the one account line.
- `member_online_day` is summarised: one line per week online.
- A reveal is the ledger's `reveal_liker` debit, whose metadata names the
  liker; `revealed_likers` holds the same reveals without the cost.

Every timestamp leaves as UTC. Naive columns (`skipped`, `visited`,
`messaged`, `person_report`, `person.sign_up_time`,
`verification_job.expires_at`) hold UTC, so each is compared against a
naive bound and converted with AT TIME ZONE 'UTC', which keeps their
indexes usable.

A deleted member's rows go with their account (every reference here
cascades), except in the member's own copy of a conversation and in a
reveal's metadata, which name the other member by uuid. Those lines carry
no other member and the detail 'deleted'.
"""
from __future__ import annotations

from service.admin.queries.members import member_sql

# The filters on the timeline (the design brief's All, Interactions,
# Messages, Reports, Money, Account, Community).
TYPES = ('interactions', 'messages', 'reports', 'money', 'account', 'community')

# Every branch returns the same six columns:
#   kind      the line's kind
#   at        timestamptz, when it happened
#   other_id  the other member's person.id, when the source keeps one
#   other_ref the other member's uuid as text, when the source keeps that
#   n         a count, where the line has one
#   detail    a short code, where the line has one
#
# Bound parameters: pid (person.id), puuid (person.uuid as text), lo/hi
# (timestamptz) and lo_n/hi_n (the same as naive UTC), lim (rows per
# branch), lo_id/hi_id (the archive's id range for lo and the end of `to`)
# and hi_end, the end of the from/to range without the paging cursor.
#
# A branch holds no ORDER BY of its own: timeline_sql wraps each one in the
# outer query's full order (_ORDER), so the `lim` rows a branch gives up are
# the same rows on every page however many share one instant.


def _between(col: str, naive: bool = False) -> str:
    s = '_n' if naive else ''
    return f"{col} >= %(lo{s})s AND {col} <= %(hi{s})s"


_UTC = "AT TIME ZONE 'UTC'"

_BRANCHES: dict[str, list[str]] = {
    'interactions': [
        f"""SELECT 'like_sent' AS kind, l.created_at AS at, l.liked_id AS other_id,
                   NULL::text AS other_ref, NULL::int AS n,
                   CASE WHEN l.is_super THEN 'super' END AS detail
              FROM liked l
             WHERE l.liker_id = %(pid)s AND {_between('l.created_at')}""",
        f"""SELECT 'like_received', l.created_at, l.liker_id, NULL, NULL,
                   CASE WHEN l.is_super THEN 'super' END
              FROM liked l
             WHERE l.liked_id = %(pid)s AND {_between('l.created_at')}""",
        f"""SELECT 'pass', s.created_at {_UTC}, s.object_person_id, NULL, NULL, NULL
              FROM skipped s
             WHERE s.subject_person_id = %(pid)s AND NOT s.reported
               AND {_between('s.created_at', naive=True)}""",
        f"""SELECT 'match', m.created_at,
                   CASE WHEN m.user_a_id = %(pid)s THEN m.user_b_id ELSE m.user_a_id END,
                   NULL, NULL, NULL
              FROM ahavah_match m
             WHERE (m.user_a_id = %(pid)s OR m.user_b_id = %(pid)s)
               AND {_between('m.created_at')}""",
        # A match since ended: ahavah_match lost the row at the unmatch.
        f"""SELECT 'match', u.matched_at,
                   CASE WHEN u.user_a_id = %(pid)s THEN u.user_b_id ELSE u.user_a_id END,
                   NULL, NULL, NULL
              FROM unmatched_pair u
             WHERE (u.user_a_id = %(pid)s OR u.user_b_id = %(pid)s)
               AND u.matched_at IS NOT NULL AND {_between('u.matched_at')}""",
        f"""SELECT CASE WHEN u.unmatched_by = %(pid)s THEN 'unmatched' ELSE 'unmatched_by' END,
                   u.unmatched_at,
                   CASE WHEN u.user_a_id = %(pid)s THEN u.user_b_id ELSE u.user_a_id END,
                   NULL, NULL, NULL
              FROM unmatched_pair u
             WHERE (u.user_a_id = %(pid)s OR u.user_b_id = %(pid)s)
               AND {_between('u.unmatched_at')}""",
        f"""SELECT 'view_given', v.updated_at {_UTC}, v.object_person_id, NULL, NULL,
                   CASE WHEN v.invisible THEN 'invisible' END
              FROM visited v
             WHERE v.subject_person_id = %(pid)s AND {_between('v.updated_at', naive=True)}""",
        f"""SELECT 'view_received', v.updated_at {_UTC}, v.subject_person_id, NULL, NULL,
                   CASE WHEN v.invisible THEN 'invisible' END
              FROM visited v
             WHERE v.object_person_id = %(pid)s AND {_between('v.updated_at', naive=True)}""",
    ],
    'messages': [
        f"""SELECT 'first_message', d.created_at {_UTC}, d.object_person_id, NULL, NULL, NULL
              FROM messaged d
             WHERE d.subject_person_id = %(pid)s AND {_between('d.created_at', naive=True)}""",
        # One line per conversation: how many messages (both ways) and the
        # last one's time. Counted over the from/to range, never the paging
        # cursor, so a conversation keeps its count on every page and shows
        # once; HAVING places it on the page its last message falls on.
        # The archive's id is microseconds since the epoch shifted left 8
        # bits (service/chat/messagestorage/mam). Only id and
        # remote_bare_jid are read, both in the archive's own index.
        """SELECT 'conversation',
                  to_timestamp((MAX(a.id) >> 8) / 1000000.0),
                  NULL::int, a.other_ref, COUNT(*)::int, NULL
             FROM (SELECT split_part(mm.remote_bare_jid, '@', 1) AS other_ref, mm.id
                     FROM mam_message mm
                    WHERE mm.person_id = %(pid)s AND mm.id BETWEEN %(lo_id)s AND %(hi_id)s
                   UNION ALL
                   SELECT split_part(um.remote_bare_jid, '@', 1), um.id
                     FROM unmatched_message um
                    WHERE um.person_id = %(pid)s AND um.id BETWEEN %(lo_id)s AND %(hi_id)s
                  ) a
            GROUP BY a.other_ref
           HAVING to_timestamp((MAX(a.id) >> 8) / 1000000.0) <= %(hi)s""",
    ],
    'reports': [
        f"""SELECT 'report_made', r.reported_at {_UTC}, r.reported_id, NULL, NULL, NULL
              FROM person_report r
             WHERE r.reporter_id = %(pid)s AND {_between('r.reported_at', naive=True)}""",
        f"""SELECT 'report_received', r.reported_at {_UTC}, r.reporter_id, NULL, NULL, NULL
              FROM person_report r
             WHERE r.reported_id = %(pid)s AND {_between('r.reported_at', naive=True)}""",
    ],
    'money': [
        # Tokens in and out. A reveal names the liker it revealed.
        f"""SELECT CASE WHEN tl.reason = 'reveal_liker' THEN 'reveal' ELSE 'tokens' END,
                   tl.created_at, NULL::int,
                   CASE WHEN tl.reason = 'reveal_liker' THEN tl.metadata->>'revealed_liker_id' END,
                   tl.delta,
                   CASE WHEN tl.reason = 'reveal_liker' THEN NULL ELSE tl.reason END
              FROM token_ledger tl
             WHERE tl.person_id = %(puuid)s::uuid AND {_between('tl.created_at')}""",
        # Premium from Stripe: a subscription checkout starts it, a
        # subscription's deletion ends it. A test-mode event says so.
        # Token bundles are on the ledger above, so not here.
        f"""SELECT CASE WHEN e.event_type = 'customer.subscription.deleted'
                        THEN 'premium_ended' ELSE 'premium_started' END,
                   e.received_at, NULL::int, NULL, NULL,
                   CASE WHEN COALESCE(e.payload->>'livemode',
                                      e.payload->'data'->'object'->>'livemode') = 'true'
                        THEN NULL ELSE 'test' END
              FROM entitlement_event e
             WHERE e.app_user_id = %(pid)s::text
               AND ((e.event_type = 'checkout.session.completed'
                     AND COALESCE(e.payload->'data'->'object'->>'mode', e.payload->>'mode') = 'subscription')
                    OR e.event_type = 'customer.subscription.deleted')
               AND {_between('e.received_at')}""",
    ],
    'account': [
        f"""SELECT 'joined', p.sign_up_time {_UTC}, NULL::int, NULL, NULL, NULL
              FROM person p
             WHERE p.id = %(pid)s AND {_between('p.sign_up_time', naive=True)}""",
        f"""SELECT 'deactivated', p.admin_deactivated_at, NULL::int, NULL, NULL, 'admin'
              FROM person p
             WHERE p.id = %(pid)s AND p.admin_deactivated_at IS NOT NULL
               AND {_between('p.admin_deactivated_at')}""",
        f"""SELECT 'deletion_requested', p.deletion_requested_at, NULL::int, NULL, NULL, NULL
              FROM person p
             WHERE p.id = %(pid)s AND p.deletion_requested_at IS NOT NULL
               AND {_between('p.deletion_requested_at')}""",
        f"""SELECT 'verification', p.id_verified_at, NULL::int, NULL, NULL, 'id_passed'
              FROM person p
             WHERE p.id = %(pid)s AND p.id_verified_at IS NOT NULL
               AND {_between('p.id_verified_at')}""",
        f"""SELECT 'verification', p.id_verification_status_at, NULL::int, NULL, NULL,
                   'id_' || p.id_verification_status
              FROM person p
             WHERE p.id = %(pid)s AND p.id_verification_status IS NOT NULL
               AND p.id_verification_status_at IS NOT NULL
               AND {_between('p.id_verification_status_at')}""",
        f"""SELECT 'verification', (j.expires_at - INTERVAL '3 days') {_UTC}, NULL::int, NULL, NULL,
                   CASE j.status WHEN 'success' THEN 'photo_passed'
                                 WHEN 'failure' THEN 'photo_failed'
                                 ELSE 'photo_pending' END
              FROM verification_job j
             WHERE j.person_id = %(pid)s
               AND {_between("(j.expires_at - INTERVAL '3 days')", naive=True)}""",
        # One line per week online: the days that week, at the last time
        # seen. Counted over the from/to range only, like a conversation.
        """SELECT 'online_week', MAX(o.last_at), NULL::int, NULL,
                  COUNT(*)::int, MIN(date_trunc('week', o.day))::date::text
             FROM member_online_day o
            WHERE o.person_id = %(pid)s
              AND o.last_at >= %(lo)s AND o.first_at <= %(hi_end)s
            GROUP BY date_trunc('week', o.day)
           HAVING MAX(o.last_at) <= %(hi)s""",
    ],
    'community': [
        # A gathering made by an organiser that is this member: one made in
        # the app (0080, member_person_id) or under the member's address.
        f"""SELECT 'gathering_created', e.created_at, NULL::int, NULL, NULL, e.title
              FROM event e
              JOIN organiser og ON og.id = e.organiser_id
             WHERE (og.member_person_id = %(pid)s
                    OR og.normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s))
               AND {_between('e.created_at')}""",
        f"""SELECT 'rsvp', r.created_at, NULL::int, NULL, NULL, e.title
              FROM event_rsvp r
              JOIN event e ON e.id = r.event_id
             WHERE (r.person_id = %(pid)s
                    OR r.normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s))
               AND r.erased_at IS NULL
               AND {_between('r.created_at')}""",
        f"""SELECT 'together_started', ts.created_at, NULL::int, NULL, NULL, ts.kind
              FROM tool_session ts
             WHERE ts.owner_person_id = %(pid)s AND {_between('ts.created_at')}""",
        # The category only.
        f"""SELECT 'feedback', f.created_at, NULL::int, NULL, NULL, f.category
              FROM feedback f
             WHERE f.person_id = %(pid)s AND {_between('f.created_at')}""",
    ],
}


_COLS = 'kind, at, other_id, other_ref, n, detail'
_ORDER = ('at DESC, kind, other_id NULLS FIRST, other_ref NULLS FIRST, '
          'detail NULLS FIRST, n NULLS FIRST')


def _branch(sql: str) -> str:
    """One branch, typed, cut at the cursor and ordered on the full key
    before its LIMIT. Casting here settles a bare NULL's type, which a
    subquery would otherwise read as text."""
    return f"""(SELECT kind::text, at::timestamptz, other_id::int, other_ref::text,
                   n::int, detail::text
              FROM ({sql}) x ({_COLS})
             WHERE at <= %(hi)s
             ORDER BY {_ORDER}
             LIMIT %(lim)s)"""


def timeline_sql(types: tuple[str, ...] = TYPES) -> str:
    """The timeline for the filters in `types`, newest first.

    Each branch takes at most `lim` rows on the full key; the union is
    ordered on the same key, `skip` rows already shown at the cursor's exact
    time are passed over, and `page` + 1 rows come back (the extra one says
    whether there is more). The other member is resolved only for the rows
    returned."""
    union = '\n    UNION ALL\n    '.join(_branch(b) for t in types for b in _BRANCHES[t])
    return f"""
    WITH line AS (
        SELECT {_COLS} FROM (
    {union}
        ) b ({_COLS})
         ORDER BY {_ORDER}
        OFFSET %(skip)s LIMIT %(page)s
    )
    SELECT line.kind, line.at, line.n, line.detail,
           (line.other_id IS NOT NULL OR line.other_ref IS NOT NULL) AS has_other,
           COALESCE(oi.uuid, ou.uuid)::text AS other_uuid,
           split_part(btrim(COALESCE(oi.name, ou.name)), ' ', 1) AS other_name,
           CASE WHEN oi.id IS NOT NULL THEN NOT {member_sql('oi')}
                WHEN ou.id IS NOT NULL THEN NOT {member_sql('ou')} END AS other_staff
      FROM line
      LEFT JOIN person oi ON oi.id = line.other_id
      LEFT JOIN person ou ON ou.uuid = uuid_or_null(line.other_ref)
     ORDER BY line.{_ORDER.replace(', ', ', line.')}
"""


# The summary. Each figure is (last 7 days, last 30 days), bound as t7/t30
# (timestamptz), t7_n/t30_n (naive UTC) and id7/id30 (archive ids).
#
# Counted between MEMBERS, as everywhere in the admin (members.py): a like,
# view or message with a staff account on the other end is left out. A
# conversation or message with a member since deleted still counts: the
# member sent it. Views are the latest view of each pair (see above).
_OTHER_IS_MEMBER = member_sql('o')


def _pair(name: str, body: str) -> str:
    return f"{name} AS ({body})"


Q_MEMBER_ACTIVITY_SUMMARY = f"""
    WITH
    {_pair('likes_sent', f'''
        SELECT COUNT(*) FILTER (WHERE l.created_at > %(t7)s) AS d7, COUNT(*) AS d30
          FROM liked l JOIN person o ON o.id = l.liked_id
         WHERE l.liker_id = %(pid)s AND l.created_at > %(t30)s AND {_OTHER_IS_MEMBER}''')},
    {_pair('likes_received', f'''
        SELECT COUNT(*) FILTER (WHERE l.created_at > %(t7)s) AS d7, COUNT(*) AS d30
          FROM liked l JOIN person o ON o.id = l.liker_id
         WHERE l.liked_id = %(pid)s AND l.created_at > %(t30)s AND {_OTHER_IS_MEMBER}''')},
    {_pair('matches', f'''
        SELECT COUNT(*) FILTER (WHERE x.at > %(t7)s) AS d7, COUNT(*) AS d30
          FROM (SELECT m.created_at AS at,
                       CASE WHEN m.user_a_id = %(pid)s THEN m.user_b_id ELSE m.user_a_id END AS oid
                  FROM ahavah_match m
                 WHERE (m.user_a_id = %(pid)s OR m.user_b_id = %(pid)s) AND m.created_at > %(t30)s
                UNION ALL
                SELECT u.matched_at,
                       CASE WHEN u.user_a_id = %(pid)s THEN u.user_b_id ELSE u.user_a_id END
                  FROM unmatched_pair u
                 WHERE (u.user_a_id = %(pid)s OR u.user_b_id = %(pid)s) AND u.matched_at > %(t30)s
               ) x JOIN person o ON o.id = x.oid
         WHERE {_OTHER_IS_MEMBER}''')},
    {_pair('unmatches', f'''
        SELECT COUNT(*) FILTER (WHERE u.unmatched_at > %(t7)s) AS d7, COUNT(*) AS d30
          FROM unmatched_pair u
          JOIN person o ON o.id = CASE WHEN u.user_a_id = %(pid)s THEN u.user_b_id ELSE u.user_a_id END
         WHERE (u.user_a_id = %(pid)s OR u.user_b_id = %(pid)s) AND u.unmatched_at > %(t30)s
           AND {_OTHER_IS_MEMBER}''')},
    archive AS (
        SELECT split_part(mm.remote_bare_jid, '@', 1) AS other_ref, mm.id, mm.direction
          FROM mam_message mm
         WHERE mm.person_id = %(pid)s AND mm.id >= %(id30)s
        UNION ALL
        SELECT split_part(um.remote_bare_jid, '@', 1), um.id, um.direction
          FROM unmatched_message um
         WHERE um.person_id = %(pid)s AND um.id >= %(id30)s
    ),
    {_pair('archive_members', f'''
        SELECT a.other_ref, a.id, a.direction FROM archive a
          LEFT JOIN person o ON o.uuid = uuid_or_null(a.other_ref)
         WHERE o.id IS NULL OR {_OTHER_IS_MEMBER}''')},
    {_pair('conversations', '''
        SELECT COUNT(DISTINCT other_ref) FILTER (WHERE id >= %(id7)s) AS d7,
               COUNT(DISTINCT other_ref) AS d30
          FROM archive_members''')},
    {_pair('messages_sent', '''
        SELECT COUNT(*) FILTER (WHERE id >= %(id7)s) AS d7, COUNT(*) AS d30
          FROM archive_members WHERE direction = 'O' ''')},
    {_pair('views_given', f'''
        SELECT COUNT(*) FILTER (WHERE v.updated_at > %(t7_n)s) AS d7, COUNT(*) AS d30
          FROM visited v JOIN person o ON o.id = v.object_person_id
         WHERE v.subject_person_id = %(pid)s AND v.updated_at > %(t30_n)s AND {_OTHER_IS_MEMBER}''')},
    {_pair('views_received', f'''
        SELECT COUNT(*) FILTER (WHERE v.updated_at > %(t7_n)s) AS d7, COUNT(*) AS d30
          FROM visited v JOIN person o ON o.id = v.subject_person_id
         WHERE v.object_person_id = %(pid)s AND v.updated_at > %(t30_n)s AND {_OTHER_IS_MEMBER}''')},
    {_pair('reports_made', '''
        SELECT COUNT(*) FILTER (WHERE r.reported_at > %(t7_n)s) AS d7, COUNT(*) AS d30
          FROM person_report r
         WHERE r.reporter_id = %(pid)s AND r.reported_at > %(t30_n)s''')},
    {_pair('reports_received', '''
        SELECT COUNT(*) FILTER (WHERE r.reported_at > %(t7_n)s) AS d7, COUNT(*) AS d30
          FROM person_report r
         WHERE r.reported_id = %(pid)s AND r.reported_at > %(t30_n)s''')},
    {_pair('days_online', '''
        SELECT COUNT(*) FILTER (WHERE o.last_at > %(t7)s) AS d7, COUNT(*) AS d30
          FROM member_online_day o
         WHERE o.person_id = %(pid)s AND o.last_at > %(t30)s''')}
    SELECT
        likes_sent.d7 AS likes_sent_d7, likes_sent.d30 AS likes_sent_d30,
        likes_received.d7 AS likes_received_d7, likes_received.d30 AS likes_received_d30,
        matches.d7 AS matches_d7, matches.d30 AS matches_d30,
        unmatches.d7 AS unmatches_d7, unmatches.d30 AS unmatches_d30,
        conversations.d7 AS conversations_d7, conversations.d30 AS conversations_d30,
        messages_sent.d7 AS messages_sent_d7, messages_sent.d30 AS messages_sent_d30,
        views_given.d7 AS views_given_d7, views_given.d30 AS views_given_d30,
        views_received.d7 AS views_received_d7, views_received.d30 AS views_received_d30,
        reports_made.d7 AS reports_made_d7, reports_made.d30 AS reports_made_d30,
        reports_received.d7 AS reports_received_d7, reports_received.d30 AS reports_received_d30,
        days_online.d7 AS days_online_d7, days_online.d30 AS days_online_d30
      FROM likes_sent, likes_received, matches, unmatches, conversations, messages_sent,
           views_given, views_received, reports_made, reports_received, days_online
"""

SUMMARY_FIELDS = (
    'likes_sent', 'likes_received', 'matches', 'unmatches', 'conversations',
    'messages_sent', 'views_given', 'views_received', 'reports_made',
    'reports_received', 'days_online',
)

Q_MEMBER_FOR_ACTIVITY = """
    SELECT id, uuid::text AS uuid, email FROM person WHERE uuid = %(uuid)s::uuid
"""
