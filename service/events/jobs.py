"""The gathering jobs (TEC-1845), run hourly by the return-mail cron
(service/cron/returnmail): the reminder the day before, the organiser's
daily digest and the one invitation to join the day after (TEC-1845,
service/events/join.py).

Neither is ever queued inside one of the owner's rest periods
(service/spotlight/restdays.is_rest_period). The reminder waits for the
period to end, never past the gathering's own day before; a gathering whose
whole day before is a rest day gets none (the calendar file stands in).
A digest day inside a rest period is skipped and its RSVPs wait for the
next one. Confirm, change and cancellation mail is not held: the guest or
the organiser caused it.

Each job takes the cron's transaction. Every email's switch is read by the
queue functions, so a job does nothing while its email is off.
"""
from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta

from service.events import mail
from service.spotlight import restdays

# The reminder goes on the gathering's local day before its start, from
# 08:00 until 21:00 local time, at the first hourly tick not in a rest period.
REMINDER_HOURS = (8, 21)
DIGEST_HOUR_UTC = 12
# Gatherings near enough to be a day away somewhere on Earth.
_REMINDER_LOOKAHEAD = timedelta(days=3)


def _reminder_due(starts_at: datetime, tz: str, now: datetime) -> bool:
    zone = zoneinfo.ZoneInfo(tz)
    local_now = now.astimezone(zone)
    day_before = starts_at.astimezone(zone).date() - timedelta(days=1)
    first, last = REMINDER_HOURS
    return local_now.date() == day_before and first <= local_now.hour < last


def queue_reminders(tx, now: datetime) -> int:
    """Reminders for every confirmed guest of a gathering whose day before
    it now is. Returns how many were queued."""
    from service.events import CAMPAIGN_SWITCHES, rsvp, switch_on
    if not switch_on(CAMPAIGN_SWITCHES[mail.CAMPAIGN_REMINDER]) or restdays.is_rest_period(now):
        return 0
    events = tx.execute(
        """SELECT id, starts_at, tz FROM event
            WHERE status = 'published' AND paused_at IS NULL
              AND starts_at > %(now)s AND starts_at <= %(until)s""",
        dict(now=now, until=now + _REMINDER_LOOKAHEAD)).fetchall()
    n = 0
    for ev in events:
        if not _reminder_due(ev['starts_at'], ev['tz'], now):
            continue
        guests = tx.execute(
            """SELECT * FROM event_rsvp WHERE event_id = %(e)s AND status = 'going'
                  AND confirmed_at IS NOT NULL AND erased_at IS NULL ORDER BY id""",
            dict(e=ev['id'])).fetchall()
        for r in guests:
            # Check first, so a repeat tick or an unreachable guest retires
            # no link: the token is reissued only for an email about to go.
            if mail.reminder_already(tx, r['id'], ev['starts_at']) or mail._guest_to(tx, dict(r)) is None:
                continue
            token = rsvp.reissue_token(tx, r['id'])
            if mail.queue_reminder(tx, r['id'], token) is not None:
                n += 1
    return n


def queue_digests(tx, now: datetime) -> int:
    """At the first tick from 12:00 UTC that is not in a rest period, one
    digest per published gathering (not ended more than a day ago) with
    RSVPs confirmed since its last digest. Returns how many were queued."""
    if now.hour < DIGEST_HOUR_UTC or restdays.is_rest_period(now):
        return 0
    events = tx.execute(
        """SELECT DISTINCT e.id FROM event e JOIN event_rsvp r ON r.event_id = e.id
            WHERE e.status = 'published' AND e.ends_at > %(since)s
              AND r.status = 'going' AND r.confirmed_at IS NOT NULL
              AND r.digested_at IS NULL AND r.erased_at IS NULL
            ORDER BY e.id""",
        dict(since=now - timedelta(days=1))).fetchall()
    day = now.date()
    return sum(1 for ev in events if mail.queue_digest(tx, ev['id'], day) is not None)


def queue_join_invites(tx, now: datetime) -> int:
    """The invitation to join, for the confirmed going guests who ticked
    the box at a published gathering that ended in the last 7 days, when
    join.invite_due says so in the gathering's own zone. A cancelled or
    paused gathering sends none. Returns how many were queued."""
    from service.events import join, switch_on
    from service.events import CAMPAIGN_SWITCHES
    if not switch_on(CAMPAIGN_SWITCHES[mail.CAMPAIGN_JOIN_INVITE]):
        return 0
    events = tx.execute(
        """SELECT id, slug, title, mode, ends_at, tz FROM event
            WHERE status = 'published' AND paused_at IS NULL
              AND ends_at <= %(now)s AND ends_at > %(since)s
            ORDER BY id""",
        dict(now=now, since=now - join.INVITE_WINDOW)).fetchall()
    n = 0
    for ev in events:
        if not join.invite_due(ev['ends_at'], ev['tz'], now):
            continue
        guests = tx.execute(
            """SELECT * FROM event_rsvp WHERE event_id = %(e)s AND status = 'going'
                  AND confirmed_at IS NOT NULL AND erased_at IS NULL AND marketing_consent
                  AND person_id IS NULL AND lead_id IS NOT NULL
                ORDER BY id""",
            dict(e=ev['id'])).fetchall()
        for r in guests:
            if mail.queue_join_invite(tx, dict(r), dict(ev), now) is not None:
                n += 1
    return n
