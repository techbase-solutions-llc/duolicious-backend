"""Inviting gathering guests who are not members to join Ahavah (TEC-1845,
docs/superpowers/plans/2026-10-22-events-invite-to-join.md).

  join_url           the sign-up link that credits the gathering
                     ({WEB_BASE_URL}/auth/sign-up?src=event%3A{slug}); the
                     slug only, never an address or a token
  offers_join        whether one RSVP may see the "Join Ahavah" block:
                     the block's switch, a visitor (no person_id) with a
                     lead, an address no member holds now and a lead that
                     has not left the news mail (Owner decision 7)
  mail_block_allowed the rest-day rule on top, for the confirm and reminder
                     emails: never inside a rest period or past the last
                     date the owner's calendar has been read for
  invite_due         when the one invitation to join may be queued: the
                     gathering's local days after it ends, 10:00 to 20:00
                     gathering time, never inside or within REST_MARGIN of a
                     rest period nor past the known calendar, and only
                     inside INVITE_WINDOW (Owner decisions 3 and 4)

Members never: the address is checked against person at every build, so a
guest who joined since the RSVP sees no block.
"""
from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta
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
    from service.leads import lead_unsubscribed
    if not switch_on(BLOCK_SWITCH):
        return False
    if r.get('person_id') is not None or r.get('lead_id') is None:
        return False
    if is_member_address(tx, r.get('normalized_email')):
        return False
    return not lead_unsubscribed(tx, r['lead_id'])


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
