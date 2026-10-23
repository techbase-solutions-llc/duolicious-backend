"""Gatherings, release 1 (TEC-1845).

docs/superpowers/specs/2026-10-13-events-design.md and
docs/superpowers/plans/2026-10-21-events-release-1.md.

  fields      slugs, regions, feasts, tags, draft validation, text flags and
              the words for a gathering's time
  organisers  the request to host, the magic link, the organiser from a token
  manage      create, edit, cover, publish, cancel, the organiser's lists,
              the RSVP list and attendance
  public      the list by region, one gathering, page views
  rsvp        RSVP without an account, confirm, view, cancel
  ics         the calendar file
  mail        every gathering email, its queueing and its proof preview
  jobs        the reminder the day before and the organiser's digest
  admin       approvals, pause, the badge and the figures (counts only)
  invites     leaders asking Ahavah to come
  retention   the sweep, deleting with the account, linking at sign-up

Dark until launch: while events_live is off (AHAVAH_EVENTS_LIVE_ENABLED,
service/campaigns/switches.py) every gathering route but /events/status
answers 404 and no gathering email is queued or sent, whichever way its own
switch is set. The surfaces opened later (hosting, the list, the invite
page) and each email have their own switch, which counts only once
events_live is on. The proofs (scripts/send_event_proofs.py) and Admin >
Events work either way.
"""
from __future__ import annotations

from typing import Literal

from service.campaigns.switches import enabled

# Each gathering email's outbox campaign and its switch. The outbox drain
# reads it again at send time (service/campaigns/outbox.py), so a switch
# turned off after a row was queued stops it.
CAMPAIGN_SWITCHES: dict[str, str] = {
    'event_confirm': 'events_confirm_email',
    'event_reminder': 'events_reminder_email',
    'event_change': 'events_change_email',
    'event_cancelled': 'events_cancel_email',
    'event_digest': 'events_digest_email',
    'event_manage': 'events_manage_email',
    'event_organiser_note': 'events_manage_email',
    # The one invitation to join, the day after (TEC-1845). The join block
    # has no campaign of its own: it rides in event_confirm and
    # event_reminder and is read when they are built.
    'event_join_invite': 'events_join_invite_email',
}


class EventError(Exception):
    """A refusal the routes answer as {error: reason} with this status."""

    def __init__(self, reason: str, status: int = 400, **extra):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.extra = extra


def live() -> bool:
    """Gatherings are launched: the routes answer."""
    return enabled('events_live')


def surface_on(name: Literal['events_hosting', 'events_list', 'events_invite']) -> bool:
    """A surface opened after launch, which counts only once live."""
    return live() and enabled(name)


def switch_on(name: str) -> bool:
    """A switch (an email's, usually) which counts only once live."""
    return live() and enabled(name)


def member_email_on(name: Literal['e2_gatherings', 'welcome_gatherings']) -> bool:
    """Gatherings in a member email: the section in E2 or the welcome's
    mention. Each links to /events, which answers 404 until the list is
    open, so each needs events_live and events_list as well as its own."""
    return surface_on('events_list') and enabled(name)
