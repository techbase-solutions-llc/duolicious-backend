"""The quick-question pushes (TEC-1845, spec "Notifications").

  match_question  from 24 hours after a match in which nobody has written,
                  once per match, to both members (owner decision 3). Not
                  held by the gap: it goes once and a hold would lose it.
  question        this week's question, 18:00 to 21:00 the member's local
                  time on the drop day, to members active in the last 60
                  days who have not answered it. Held by the gap.
  launch          the launch week's question push (queue_launch_pushes).

They share 1 push per member per question week (from 00:00 Barbados on the
current drop's live_on). The cron runs match_question first, so when both
are due the silent match wins and no weekly push follows that week.

Every push: only to a member with push_questions on (default on) and a
subscription; never to one who left campaign emails, to staff, to a test or
suppressed address; never in quiet hours (21:00 to 08:00 local, from
push_subscription.tz, US Eastern when missing); never in a rest period or
past the known calendar (schedule.resting); never after 2 question pushes
with no visit since. send_to_user_safe only, never notify(), which would
fall back to email. Each is logged in push_send_log in the job's
transaction and sent after it commits (held.after_commit); one that fails
gives its log rows back, to be tried next tick.

Held: nothing goes unless its switch is on (service/campaigns/switches.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from emails.base import suppressed_sql_pattern
from service.admin.queries.members import member_sql
from service.campaigns import held, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.switches import enabled
from service.growth.queries import _excluded
from service.questions import copy
from service.questions.member import ensure_match_question
from service.questions.schedule import current_drop, resting, week_starts_at

QUESTION = 'question'
MATCH_QUESTION = 'match_question'
LAUNCH = 'questions_launch'
LAUNCH_ID = 'launch'

DEFAULT_TZ = ZoneInfo('America/New_York')
QUIET_FROM, QUIET_UNTIL = 21, 8
EVENING = 18
ACTIVE_DAYS = 60
MAX_UNVISITED = 2


def PUSH_READY() -> bool:
    from service.notifications import PUSH_ENABLED
    return PUSH_ENABLED


def _push(person_id: int, title: str, body: str, url: str, tag: str) -> None:
    from service.notifications import send_to_user_safe
    send_to_user_safe(person_id, title, body, url, tag, event_kind='questions')


def zone(tz: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz) if tz else DEFAULT_TZ
    except Exception:
        return DEFAULT_TZ


def quiet(local: datetime) -> bool:
    return local.hour >= QUIET_FROM or local.hour < QUIET_UNTIL


def _evening(drop: dict, local: datetime) -> bool:
    return local.date() == drop['live_on'] and EVENING <= local.hour < QUIET_FROM


def _audience(alias: str = 'p') -> str:
    return f"""{alias}.activated AND {alias}.deletion_requested_at IS NULL
       AND {member_sql(alias)}
       AND lower({alias}.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql('campaigns', f'{alias}.id')})
       AND NOT ({suppressed_predicate_sql(f'{alias}.email')})
       AND COALESCE((SELECT np.push_questions FROM notification_preference np
                      WHERE np.person_id = {alias}.id), TRUE)
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {alias}.id)"""


def _member_cols(alias: str = 'p') -> str:
    """The member's id, newest known time zone and how many question
    pushes have gone since their last visit."""
    return f"""{alias}.id AS person_id,
       (SELECT ps.tz FROM push_subscription ps
         WHERE ps.person_id = {alias}.id AND ps.tz IS NOT NULL
         ORDER BY ps.updated_at DESC LIMIT 1) AS tz,
       (SELECT count(*) FROM push_send_log l
         WHERE l.person_id = {alias}.id
           AND l.campaign IN ('{QUESTION}', '{MATCH_QUESTION}')
           AND l.sent_at > COALESCE({alias}.last_online_time, '-infinity'::timestamptz)) AS unvisited"""


_Q_PUSHED_THIS_WEEK = f"""
    SELECT 1 FROM push_send_log l
     WHERE l.person_id = %(p)s
       AND ((l.campaign = '{QUESTION}' AND l.campaign_id = %(week)s)
            OR (l.campaign = '{MATCH_QUESTION}' AND l.sent_at >= %(since)s))
     LIMIT 1
"""


def _week(drop: Optional[dict], now: datetime) -> tuple[str, datetime]:
    """(the week's key, when the week began). Before the first drop there is
    no week key, and the last 7 days stand in for the week."""
    if drop is None:
        return '', now - timedelta(days=7)
    return drop['live_on'].isoformat(), week_starts_at(drop['live_on'])


def _pushed_this_week(tx, person_id: int, week: str, since: datetime) -> bool:
    return tx.execute(_Q_PUSHED_THIS_WEEK, dict(p=person_id, week=week, since=since)).fetchone() is not None


def _log(tx, campaign: str, cid: str, person_id: int) -> bool:
    return tx.execute(
        """INSERT INTO push_send_log (person_id, campaign, campaign_id)
           VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
        dict(p=person_id, c=campaign, cid=cid)).fetchone() is not None


def _unlog(logs: list[tuple[str, str]], person_id: int) -> None:
    """Runs in its own transaction, from held.run_after_commit."""
    from database import api_tx
    with api_tx() as tx:
        for campaign, cid in logs:
            tx.execute("""DELETE FROM push_send_log
                           WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                       dict(p=person_id, c=campaign, cid=cid))


def _deliver(tx, person_id: int, logs: list[tuple[str, str]], push: dict) -> bool:
    """Log every key, then push after the commit. Callers check every key
    first, so a key already taken here means another tick got there; that
    member is skipped."""
    for campaign, cid in logs:
        if not _log(tx, campaign, cid, person_id):
            return False
    held.after_commit(lambda: _push(person_id, push['title'], push['body'], push['url'], push['tag']),
                      on_failure=lambda: _unlog(logs, person_id))
    return True


def _params(**extra) -> dict:
    return dict(ex=_excluded(), sup=suppressed_sql_pattern(), **extra)


_Q_SILENT = f"""
    WITH m AS (
        SELECT match_id, user_a_id, user_b_id
          FROM ahavah_match
         WHERE created_at <= NOW() - make_interval(hours => 24)
           AND created_at > NOW() - make_interval(days => 7)
           AND NOT EXISTS (SELECT 1 FROM messaged x
                            WHERE (x.subject_person_id = user_a_id AND x.object_person_id = user_b_id)
                               OR (x.subject_person_id = user_b_id AND x.object_person_id = user_a_id))
           AND NOT is_blocked_pair(user_a_id, user_b_id)
    ), sides AS (
        SELECT match_id, user_a_id, user_b_id, user_a_id AS pid, user_b_id AS other FROM m
        UNION ALL
        SELECT match_id, user_a_id, user_b_id, user_b_id, user_a_id FROM m
    )
    SELECT s.match_id::text AS match_id, s.user_a_id, s.user_b_id,
           o.uuid::text AS other_uuid, {_member_cols()}
      FROM sides s
      JOIN person p ON p.id = s.pid
      JOIN person o ON o.id = s.other AND o.activated AND o.deletion_requested_at IS NULL
     WHERE {_audience()}
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{MATCH_QUESTION}'
                          AND l.campaign_id = s.match_id::text)
     ORDER BY s.match_id, p.id
"""


def queue_match_question_pushes(tx, now: datetime) -> int:
    if not enabled('match_question_push') or not PUSH_READY() or resting(now):
        return 0
    week, since = _week(current_drop(tx, now), now)
    n = 0
    for r in tx.execute(_Q_SILENT, _params()).fetchall():
        if int(r['unvisited']) >= MAX_UNVISITED or quiet(now.astimezone(zone(r['tz']))):
            continue
        if _pushed_this_week(tx, r['person_id'], week, since):
            continue
        if ensure_match_question(tx, r['match_id'], r['user_a_id'], r['user_b_id']) is None:
            continue
        if _deliver(tx, r['person_id'], [(MATCH_QUESTION, r['match_id'])],
                    copy.match_question_push(r['other_uuid'], r['match_id'])):
            n += 1
    return n


_Q_WEEKLY = f"""
    SELECT {_member_cols()}
      FROM person p
     WHERE {_audience()}
       AND p.last_online_time > NOW() - make_interval(days => {ACTIVE_DAYS})
       AND NOT EXISTS (SELECT 1 FROM prompt_answer a
                        WHERE a.person_id = p.id AND a.prompt_key = %(key)s)
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{QUESTION}'
                          AND l.campaign_id = %(week)s)
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def queue_weekly_question_pushes(tx, now: datetime) -> int:
    if not enabled('question_push') or not PUSH_READY() or resting(now):
        return 0
    drop = current_drop(tx, now)
    if drop is None:
        return 0
    week, since = _week(drop, now)
    push = copy.weekly_push(week, drop['question'])
    n = 0
    for r in tx.execute(_Q_WEEKLY, _params(key=drop['question']['key'], week=week)).fetchall():
        if int(r['unvisited']) >= MAX_UNVISITED or not _evening(drop, now.astimezone(zone(r['tz']))):
            continue
        if _pushed_this_week(tx, r['person_id'], week, since):
            continue
        if _deliver(tx, r['person_id'], [(QUESTION, week)], push):
            n += 1
    return n
