"""Where a lead or a member came from, on one taxonomy (TEC-1845).

Growth spec, Dashboard: a Sources table compares a game player with an
event guest only if both are written the same way. Every value is `<kind>`
or `<kind>:<detail>`:

  tool:game-me  tool:game-us  tool:knows-me  tool:checklist
  event:{slug}  alert:visitor  intro  mentor
  referral:{code}  utm:{source}/{campaign}  site:{host}

`site:{host}` is not in the spec's list. Before this, a referring host was
written bare ('www.google.com'), and it needs a kind like every other value.
Migration 0066 moved the old values onto these shapes.
"""
from __future__ import annotations

import re
from typing import Optional

TOOL_SOURCES = ('tool:game-me', 'tool:game-us', 'tool:knows-me', 'tool:checklist')
ALERT_VISITOR = 'alert:visitor'
INTRO = 'intro'
MENTOR = 'mentor'
# What the marriage checklist page sends to /check-otp today.
LEGACY_CHECKLIST = 'marriage_checklist'

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
# event:{slug}:{yyyymmdd}:d10, an event post's request key
# (service/spotlight/growthposts.py), must fit the queue's 64 characters.
EVENT_SLUG_MAX = 45


def _is_slug(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= EVENT_SLUG_MAX and bool(SLUG_RE.match(value))


def event_source(slug: str) -> str:
    if not _is_slug(slug):
        raise ValueError('bad_slug')
    return f'event:{slug}'


def referral_source(code: str) -> str:
    return f'referral:{code.strip().upper()}'


def utm_label(source: str, campaign: Optional[str]) -> str:
    s = source.strip().lower()
    c = (campaign or '').strip().lower()
    return f'utm:{s}/{c}' if c else f'utm:{s}'


def site_source(host: str) -> str:
    return f'site:{host.strip().lower()}'


def canonical_tool_source(value: Optional[str]) -> Optional[str]:
    """A /check-otp `source` as stored: the checklist's old name reads as
    tool:checklist, anything that is not a tool reads as None."""
    if value == LEGACY_CHECKLIST:
        return 'tool:checklist'
    return value if value in TOOL_SOURCES else None


def signup_source(value: object) -> Optional[str]:
    """A /check-otp `source` as stored on a new onboardee: a tool value
    (canonical_tool_source), or `event:{slug}` from a gathering's join
    link when the slug is well formed, else None. The caller still checks
    that the gathering exists (TEC-1845, inviting guests to join)."""
    if not isinstance(value, str):
        return None
    tool = canonical_tool_source(value)
    if tool:
        return tool
    if value.startswith('event:') and is_lead_source(value):
        return value
    return None


def is_event_source(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith('event:')


def is_lead_source(value: object) -> bool:
    """The sources a lead row may carry: where someone gave an email before
    joining. intro and mentor are sign-up sources the matchmaker writes on
    person.lead_source; nobody gives their own email there."""
    if not isinstance(value, str):
        return False
    if value in TOOL_SOURCES or value == ALERT_VISITOR:
        return True
    return value.startswith('event:') and _is_slug(value[len('event:'):])


def source_kind(value: Optional[str]) -> str:
    return value.split(':', 1)[0] if value else 'unknown'
