"""The alert notices (TEC-1845): a count, never who.

A member hears at most once a day, at the first hourly tick at or after
12:00 UTC; a visitor at most once a week, on Thursday from 12:00 UTC, since
4.5 says "this week". Neither is queued inside one of the owner's rest
periods (service/spotlight/restdays.py): the count carries to the next run.

Who counts: someone who joined since the alert's last count and whom the
deck would show the owner (service/search/predicates.deck_base_sql), inside
the criteria (criteria.fits_sql). For a visitor the same without the pair
checks.

Channels, for a member: push when the alert's push is on, the push switch
is on and they have a live subscription; email when the alert's email is
on, or when push is on but cannot reach them (1.5: "Until then we will
email you"). When the email goes and the weekly likes email would count
likes for them, it carries the 4.3 block and stamps likes_told_at, and
that week's likes email skips them (emails/likes_waiting_weekly.py): one
email for both reasons.

Both jobs run in the returnmail cron before likes_waiting.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from service.admin.queries.members import member_sql
from service.matchmaker import mail, surface_on, switch_on
from service.matchmaker.alerts import stop_token
from service.matchmaker.criteria import fit_params, fits_sql
from service.spotlight import restdays

MEMBER_HOUR_UTC = 12
VISITOR_WEEKDAY = 3   # Thursday (datetime.weekday)
VISITOR_HOUR_UTC = 12

_Q_MEMBER_ALERTS = f"""
    SELECT a.id, a.person_id, a.criteria, a.notify_push, a.notify_email, a.counted_since,
           a.likes_told_at
      FROM match_alert a
      JOIN person p ON p.id = a.person_id
     WHERE a.active AND a.confirmed_at IS NOT NULL
       AND p.activated AND p.deletion_requested_at IS NULL
       AND {member_sql('p')}
       AND (a.last_sent_at IS NULL OR a.last_sent_at < %(day)s)
     ORDER BY a.id
"""

_Q_GENDERS = 'SELECT gender_id FROM search_preference_gender WHERE person_id = %(p)s'

_Q_LIVE_SUBSCRIPTION = 'SELECT 1 FROM push_subscription WHERE person_id = %(p)s LIMIT 1'

_Q_VISITOR_ALERTS = """
    SELECT a.id, a.lead_id, a.first_name, a.criteria, a.counted_since, l.email
      FROM match_alert a
      JOIN lead l ON l.id = a.lead_id
     WHERE a.active AND a.confirmed_at IS NOT NULL
       AND l.person_id IS NULL AND l.converted_at IS NULL AND l.unsubscribed_at IS NULL
       AND (a.last_sent_at IS NULL OR a.last_sent_at < %(week)s)
     ORDER BY a.id
"""

_Q_NOTICE = """
    INSERT INTO match_alert_notice (alert_id, audience, members, window_start, window_end,
                                    by_push, by_email)
    VALUES (%(a)s, %(aud)s, %(n)s, %(ws)s, %(we)s, %(bp)s, %(be)s)
"""


def _count(tx, c: dict, *, gender_ids: list[int], since, until, owner_id: Optional[int]) -> int:
    sql = f"SELECT count(*) AS n FROM person p WHERE {fits_sql('%(owner)s' if owner_id is not None else None)}"
    params = fit_params(c, gender_ids=gender_ids, since=since, until=until, owner_id=owner_id)
    return int(tx.execute(sql, params).fetchone()['n'])


def _genders(tx, person_id: int) -> list[int]:
    return [r['gender_id'] for r in tx.execute(_Q_GENDERS, dict(p=person_id)).fetchall()]


def _likes_waiting(tx, person_id: int) -> int:
    """The likes the weekly likes email would count for this member now, or
    0 (likes_waiting_weekly._Q_DUE, for one member)."""
    from emails import likes_waiting_weekly as lw
    from emails.base import suppressed_sql_pattern
    from service.campaigns.switches import enabled
    from service.growth.queries import _excluded
    if not enabled(lw.SWITCH):
        return 0
    row = tx.execute(lw.Q_DUE_FOR, dict(pid=person_id, ex=_excluded(),
                                        sup=suppressed_sql_pattern())).fetchone()
    return int(row['likes']) if row else 0


def queue_member_notices(tx, now: datetime) -> int:
    """Each member's notice for the day, at most one. Returns how many
    notices went."""
    if not surface_on('matchmaker_alerts') or now.hour < MEMBER_HOUR_UTC:
        return 0
    if restdays.is_rest_period(now):
        return 0
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    email_on = mail.campaign_on(mail.CAMPAIGN_ALERT)
    push_on = switch_on('matchmaker_alert_push')
    sent = 0
    for a in tx.execute(_Q_MEMBER_ALERTS, dict(day=day)).fetchall():
        n = _count(tx, a['criteria'], gender_ids=_genders(tx, a['person_id']),
                   since=a['counted_since'], until=now, owner_id=a['person_id'])
        if n < 1:
            continue
        by_push = bool(a['notify_push'] and push_on
                       and tx.execute(_Q_LIVE_SUBSCRIPTION, dict(p=a['person_id'])).fetchone())
        wants_email = a['notify_email'] or (a['notify_push'] and not by_push)
        by_email = False
        likes = 0
        if wants_email and email_on:
            likes = _likes_waiting(tx, a['person_id'])
            subject, body = mail.alert_email(n, mail.see_who_joined_url(),
                                             mail.stop_url(stop_token(a['id'])), likes=likes)
            queued = mail.guarded(tx, 'mm_alert', lambda: mail.queue_member(
                tx, campaign=mail.CAMPAIGN_ALERT, campaign_id=f"{a['id']}:{now:%Y%m%d}",
                person_id=a['person_id'], subject=subject, html_=body))
            by_email = queued is not None
        if by_push:
            mail.push_after_commit(a['person_id'], mail.alert_push(n), 'matchmaker_alert_push')
        if not (by_push or by_email):
            continue
        tx.execute(_Q_NOTICE, dict(a=a['id'], aud='member', n=n, ws=a['counted_since'], we=now,
                                   bp=by_push, be=by_email))
        tx.execute("""UPDATE match_alert SET counted_since = %(now)s, last_sent_at = %(now)s,
                             likes_told_at = CASE WHEN %(told)s THEN %(now)s ELSE likes_told_at END
                       WHERE id = %(i)s""",
                   dict(now=now, told=bool(by_email and likes), i=a['id']))
        sent += 1
    return sent


def _week_start(now: datetime) -> datetime:
    from datetime import timedelta
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def queue_visitor_notices(tx, now: datetime) -> int:
    """Each visitor's notice for the week, on Thursday from 12:00 UTC, at
    most one per ISO week. Returns how many went."""
    from service.campaigns import outbox
    from service.matchmaker.regions import codes_in
    if not surface_on('matchmaker_visitor_alerts'):
        return 0
    if now.weekday() != VISITOR_WEEKDAY or now.hour < VISITOR_HOUR_UTC:
        return 0
    if restdays.is_rest_period(now) or not mail.campaign_on(mail.CAMPAIGN_VISITOR_ALERT):
        return 0
    year, week, _ = now.isocalendar()
    genders = {r['name'].lower(): r['id'] for r in tx.execute(
        "SELECT id, name FROM gender WHERE name IN ('Man', 'Woman')").fetchall()}
    sent = 0
    for a in tx.execute(_Q_VISITOR_ALERTS, dict(week=_week_start(now))).fetchall():
        c = a['criteria']
        n = _count(tx, dict(c, countries=codes_in([c['region']]) if c.get('region') else []),
                   gender_ids=[genders[c['looking_for']]], since=a['counted_since'], until=now,
                   owner_id=None)
        if n < 1:
            continue
        subject, body = mail.visitor_alert_email(n, a['first_name'], mail.stop_url(stop_token(a['id'])))
        queued = mail.guarded(tx, 'mm_visitor_alert', lambda: outbox.enqueue_for_lead(
            tx, campaign=mail.CAMPAIGN_VISITOR_ALERT, campaign_id=f"{a['id']}:{year}w{week:02d}",
            lead_id=a['lead_id'], email=a['email'], subject=subject, html=body,
            from_addr=mail.FROM_ADDR, list_unsubscribe=None, marketing=True, requested=True))
        if queued is None:
            continue
        tx.execute(_Q_NOTICE, dict(a=a['id'], aud='visitor', n=n, ws=a['counted_since'], we=now,
                                   bp=False, be=True))
        tx.execute('UPDATE match_alert SET counted_since = %(now)s, last_sent_at = %(now)s '
                   'WHERE id = %(i)s', dict(now=now, i=a['id']))
        sent += 1
    return sent


def new_fit_ids(tx, person_id: int) -> list[int]:
    """The members the latest notice's window counted who still fit, for
    "See who joined" (1.13): Discover puts them first."""
    row = tx.execute(
        """SELECT a.criteria, n.window_start, n.window_end
             FROM match_alert a
             JOIN match_alert_notice n ON n.alert_id = a.id
            WHERE a.person_id = %(p)s
            ORDER BY n.created_at DESC, n.id DESC LIMIT 1""", dict(p=person_id)).fetchone()
    if row is None:
        return []
    params = fit_params(row['criteria'], gender_ids=_genders(tx, person_id),
                        since=row['window_start'], until=row['window_end'], owner_id=person_id)
    return [r['id'] for r in tx.execute(
        f"SELECT p.id FROM person p WHERE {fits_sql('%(owner)s')} ORDER BY p.sign_up_time DESC LIMIT 200",
        params).fetchall()]
