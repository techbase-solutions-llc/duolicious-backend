"""Inviting gathering guests who are not members to join Ahavah (TEC-1845,
docs/superpowers/plans/2026-10-22-events-invite-to-join.md).

  join_url           the sign-up link that credits the gathering
                     ({WEB_BASE_URL}/auth/sign-up?src=event%3A{slug}); the
                     slug only, never an address or a token
  offers_join        whether one RSVP may see the "Join Ahavah" block:
                     the block's switch, a visitor (no person_id) with a
                     lead, an address no member holds now and an address
                     no lead row of which has left the news mail (Owner
                     decision 7)
  mail_block_allowed the rest-day rule on top, for the confirm and reminder
                     emails: never inside a rest period or past the last
                     date the owner's calendar has been read for
  invite_due         when the one invitation to join may be queued: the
                     gathering's local days after it ends, 10:00 to 20:00
                     gathering time, never inside or within REST_MARGIN of a
                     rest period nor past the known calendar, and only
                     inside INVITE_WINDOW (Owner decisions 3 and 4)
  invite_lapsed,     the same rules again when the outbox drain comes to
  invite_hold        send a queued invitation: dropped once the window has
                     closed, held (never dropped) while inside it during a
                     rest period or past the known calendar
  mark_block,        the join block wrapped in markers, so the drain can
  strip_block        take it out of a queued confirm or reminder email when
                     the address has joined or left the news since

Members never: the address is checked against person at every build, so a
guest who joined since the RSVP sees no block, and again at the send.
"""
from __future__ import annotations

import re
import zoneinfo
from datetime import datetime, time, timedelta
from typing import Optional
from urllib.parse import quote

from service.config import WEB_BASE_URL
from service.leads.sources import event_source

BLOCK_SWITCH = 'events_join_block'

# The invitation (Owner decision 3): local hours in the gathering's own
# zone, [first, last); the window after ends_at; the margin kept before a
# rest period, because the outbox drain may send a while after queueing.
INVITE_HOURS = (10, 20)
INVITE_WINDOW = timedelta(days=7)
REST_MARGIN = timedelta(hours=2)


def join_url(slug: str) -> str:
    """Raises ValueError for a slug that is not well formed."""
    return f'{WEB_BASE_URL}/auth/sign-up?src=' + quote(event_source(slug), safe='')


def is_member_address(tx, normalized_email: Optional[str]) -> bool:
    if not normalized_email:
        return False
    return tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                      dict(ne=normalized_email)).fetchone() is not None


def offers_join(tx, r: dict) -> bool:
    """For one event_rsvp row. Does not look at confirmed_at or status:
    the confirm email is built before confirming, so the callers keep those
    conditions (rsvp_view: confirmed and going)."""
    from service.events import switch_on
    from service.leads import address_unsubscribed, lead_unsubscribed
    if not switch_on(BLOCK_SWITCH):
        return False
    if r.get('person_id') is not None or r.get('lead_id') is None:
        return False
    if is_member_address(tx, r.get('normalized_email')):
        return False
    return not (lead_unsubscribed(tx, r['lead_id'])
                or address_unsubscribed(tx, r.get('normalized_email')))


def mail_block_allowed(now: datetime) -> bool:
    from service.spotlight import restdays
    return not restdays.is_rest_period(now) and not restdays.is_beyond_known(now)


def invite_due(ends_at: datetime, tz: str, now: datetime) -> bool:
    """True when the invitation for a gathering that ended at `ends_at` may
    be queued at `now`. Past KNOWN_THROUGH nothing is due (Owner decision
    4): an invitation whose window closes in that time is never sent."""
    from service.spotlight import restdays
    zone = zoneinfo.ZoneInfo(tz)
    local_now = now.astimezone(zone)
    first, last = INVITE_HOURS
    if local_now.date() <= ends_at.astimezone(zone).date():
        return False
    if not first <= local_now.hour < last or now >= ends_at + INVITE_WINDOW:
        return False
    return not (restdays.is_rest_period(now) or restdays.is_rest_period(now + REST_MARGIN)
                or restdays.is_beyond_known(now + REST_MARGIN))


# ---------------------------------------------------------------------------
# At the send (service/campaigns/outbox.py). The job queues an invitation
# only at a moment invite_due allows, with REST_MARGIN for a drain that is a
# little late; a drain that is much later (the cron down through a deploy,
# an SMTP outage, a backlog) reads the rules again here.
# ---------------------------------------------------------------------------

def invite_lapsed(ends_at: datetime, now: datetime) -> bool:
    """The 7 days after the gathering have passed: the invitation is not
    sent at all. The address keeps its lead_join_invite record: it had its
    one invitation."""
    return now >= ends_at + INVITE_WINDOW


def invite_hold(ends_at: datetime, tz: str, now: datetime) -> Optional[tuple[str, datetime]]:
    """None when a queued invitation may go at `now`, else (reason, until):
    'unknown' past KNOWN_THROUGH, 'rest_day' inside a rest period. `until`
    is the first whole hour of the gathering's zone at which invite_due
    would queue it, never past the end of the window, where invite_lapsed
    drops it. Past the known calendar it looks again within the hour, so an
    extended calendar lets it go inside the window."""
    from service.spotlight import restdays
    if restdays.is_beyond_known(now):
        reason = 'unknown'
    elif restdays.is_rest_period(now):
        reason = 'rest_day'
    else:
        return None
    window_end = ends_at + INVITE_WINDOW
    if reason == 'unknown':
        return reason, min(now + timedelta(hours=1), window_end)
    local = now.astimezone(zoneinfo.ZoneInfo(tz))
    at = local.replace(minute=0, second=0, microsecond=0).astimezone(now.tzinfo) + timedelta(hours=1)
    # Past the known calendar nothing is due: from there it waits as
    # 'unknown' does, an hour at a time.
    unknown_from = datetime.combine(restdays.KNOWN_THROUGH + timedelta(days=1), time(0, 0),
                                    restdays.BARBADOS)
    while at < min(window_end, unknown_from):
        if invite_due(ends_at, tz, at):
            return reason, at
        at += timedelta(hours=1)
    return reason, min(window_end, unknown_from)


# The join block in a queued confirm or reminder email. The email is built
# once, with its token, and cannot be built again at the send, so the block
# carries markers and the drain cuts it out when the address belongs to a
# member or has left the news mail since. The email itself still goes: the
# guest asked for it.
BLOCK_START = '<!--ahavah-join-block-->'
BLOCK_END = '<!--/ahavah-join-block-->'
_BLOCK = re.compile(re.escape(BLOCK_START) + '.*?' + re.escape(BLOCK_END), re.S)


def mark_block(block_html: str) -> str:
    return BLOCK_START + block_html + BLOCK_END


def has_block(html: str) -> bool:
    return BLOCK_START in (html or '')


def strip_block(html: str) -> str:
    return _BLOCK.sub('', html)
