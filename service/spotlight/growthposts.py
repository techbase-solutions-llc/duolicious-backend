"""The scheduler's own kinds: gatherings and the question of the week (TEC-1845).

docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md,
Scheduler. Each post is about nobody, waits in awaiting_render for artwork
drawn from its Claude Design template with the row's payload
(queue.TEMPLATE_KINDS; GET /admin/growth/queue?template_render=1), then
waits in review for the owner's approval like every other post. Nothing
here publishes, and every slot is held to the owner's rest days
(service/spotlight/restdays.py).

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from service.leads.sources import event_source
from service.spotlight.queue import CAPTION_MAX, create_candidate
from service.spotlight.restdays import slot_problem

# Days before a gathering that its two feed posts go out (growth spec).
EVENT_OFFSETS_DAYS = (10, 2)
# The feed's two slots, 08:00 and 14:00 in Barbados (restdays.next_valid_slot).
SLOT_HOURS = (12, 18)
# How many days earlier a post may move when its own day is a rest day.
# Never later: a post after the gathering is no use to anyone.
EVENT_EARLIER_DAYS = 2

_Q_KEY_TAKEN = """
    SELECT 1 FROM publishing_queue WHERE request_key = %(rk)s LIMIT 1
"""

_Q_SET_SLOT = """
    UPDATE publishing_queue SET scheduled_for = %(w)s, payload = %(p)s::jsonb
     WHERE request_key = %(rk)s
"""

_Q_CANCEL_EVENT = """
    UPDATE publishing_queue SET status = 'cancelled', error = 'event_changed', updated_at = NOW()
     WHERE kind = 'event' AND request_key LIKE %(prefix)s
       AND status IN ('awaiting_render', 'review', 'scheduled', 'failed')
"""


def _check_caption(caption: object) -> str:
    if not isinstance(caption, str) or not caption.strip() or len(caption) > CAPTION_MAX:
        raise ValueError('bad_caption')
    return caption.strip()


def event_request_key(slug: str, starts_at: datetime, offset_days: int) -> str:
    """event:{slug}:{yyyymmdd of the start in UTC}:d{offset}. The date is in
    the key so a gathering moved to a new date gets new posts: a cancelled
    key stays taken, as a brand post's does."""
    return f"event:{slug}:{starts_at.astimezone(timezone.utc):%Y%m%d}:d{offset_days}"


def _event_slot(target_day: date, starts_at: datetime, now: datetime, *,
                latest: Optional[datetime] = None, strict: bool = False) -> Optional[datetime]:
    """The first slot on the post's own day, then up to EVENT_EARLIER_DAYS
    before it, that is before the gathering starts and no later than
    `latest`. At queueing (strict False) 'unknown' is allowed: a gathering
    months away is queued now, and approval and dispatch refuse it until
    the owner's calendar has been read that far (the brand rule,
    CALENDAR_HELD_KINDS). At approval (strict True) only a valid slot will
    do."""
    allowed = (None,) if strict else (None, 'unknown')
    for back in range(EVENT_EARLIER_DAYS + 1):
        day = target_day - timedelta(days=back)
        for hour in SLOT_HOURS:
            slot = datetime.combine(day, time(hour, 0), timezone.utc)
            if slot >= starts_at or (latest is not None and slot > latest):
                continue
            if slot_problem(slot, now) in allowed:
                return slot
    return None


def event_approval_slot(payload: dict, requested: Optional[datetime],
                        stored: Optional[datetime],
                        now: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[str]]:
    """Where an approval or a retry puts an event post, and why not if it
    cannot (spotlight_routes._approval_slot). Never later than the stored
    slot and never at or after the gathering's start: a post after the
    gathering is no use to anyone, so unlike a brand post it never rolls
    forward. An explicit slot is held to the calendar and to the start. A
    stored slot still valid is kept; else the latest valid slot before it,
    no more than EVENT_EARLIER_DAYS before the post's own day; else
    'too_late'. A row without the start or offset its payload should carry
    is 'too_late' as well, so it can never be published blind."""
    now = now or datetime.now(timezone.utc)
    try:
        starts_at = datetime.fromisoformat(payload['starts_at'])
        offset = int(payload['offset_days'])
    except (KeyError, TypeError, ValueError):
        return None, 'too_late'
    if starts_at.tzinfo is None or offset not in EVENT_OFFSETS_DAYS:
        return None, 'too_late'
    if requested is not None:
        problem = slot_problem(requested, now)
        if problem:
            return None, problem
        return (requested, None) if requested < starts_at else (None, 'too_late')
    if stored is None:
        return None, 'too_late'
    if stored < starts_at and slot_problem(stored, now) is None:
        return stored, None
    target_day = (starts_at - timedelta(days=offset)).astimezone(timezone.utc).date()
    slot = _event_slot(target_day, starts_at, now, latest=stored, strict=True)
    return (slot, None) if slot else (None, 'too_late')


def queue_event_posts(tx, *, slug: str, starts_at: datetime, caption: str, payload: dict,
                      created_by: str, now: Optional[datetime] = None) -> list[str]:
    """Queue a published gathering's feed posts and return the request keys
    created. A key already queued is left alone, so a repeat call changes
    nothing. `payload` is the template's data (title, date, place,
    organiser, as the events plan names them); `offset_days` and
    `starts_at` (UTC, ISO 8601) are added, and approval reads them
    (event_approval_slot)."""
    event_source(slug)
    if not isinstance(starts_at, datetime) or starts_at.tzinfo is None:
        raise ValueError('naive datetime')
    text = _check_caption(caption)
    if not isinstance(payload, dict):
        raise ValueError('bad_payload')
    now = now or datetime.now(timezone.utc)
    made: list[str] = []
    for offset in EVENT_OFFSETS_DAYS:
        rk = event_request_key(slug, starts_at, offset)
        if tx.execute(_Q_KEY_TAKEN, dict(rk=rk)).fetchone():
            continue
        target_day = (starts_at - timedelta(days=offset)).astimezone(timezone.utc).date()
        slot = _event_slot(target_day, starts_at, now)
        if slot is None:
            continue
        create_candidate(tx, kind='event', subject_person_id=None, caption=text,
                         created_by=created_by, request_key=rk,
                         target_path=f'/e/{slug}', utm_content=slug)
        tx.execute(_Q_SET_SLOT, dict(w=slot, rk=rk, p=json.dumps({
            **payload, 'offset_days': offset,
            'starts_at': starts_at.astimezone(timezone.utc).isoformat()})))
        made.append(rk)
    return made


def cancel_event_posts(tx, slug: str) -> int:
    """A gathering moved or was cancelled: every post of it not yet out (or
    on its way out) is cancelled. Returns the platform rows cancelled. A post
    already published stays; taking it down is the operator's removal."""
    event_source(slug)
    return tx.execute(_Q_CANCEL_EVENT, dict(prefix=f'event:{slug}:%')).rowcount
