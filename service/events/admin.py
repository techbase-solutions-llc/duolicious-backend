"""Admin > Events (TEC-1845): approvals, pausing, the "Ahavah will be
there" badge and the figures.

Counts only: no figure here names a guest or carries a guest's address
(admin brief decision 7). Organisers and leaders asking Ahavah to come are
shown with their contact details, since the admin must reach them.

These work whichever way the switches are set, so the owner can prepare
before launch. Every function takes the caller's transaction; the routes
write the audit row in the same one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from service.events import EventError
from service.events import mail
from service.events import manage

INVITE_STATUSES = ('new', 'contacted', 'planned', 'declined')

_Q_WAITING_ORGANISERS = """
    SELECT id, name, kind, email, city, country, about, created_at
      FROM organiser WHERE approved_at IS NULL AND revoked_at IS NULL
     ORDER BY created_at, id
"""

_Q_WAITING_EVENTS = """
    SELECT e.slug, e.title, o.name AS organiser, e.starts_at, e.flag_reason, e.created_at
      FROM event e JOIN organiser o ON o.id = e.organiser_id
     WHERE e.status = 'pending'
     ORDER BY e.created_at, e.id
"""

_Q_REQUESTS = """
    SELECT id, gathering, dates, place, numbers, contact_name, contact_email, status, notes, created_at
      FROM ahavah_invite_request ORDER BY created_at DESC, id DESC
"""

# One row per gathering, every figure a count. women_members and
# member_rsvps count confirmed RSVPs from members (decision 2).
_Q_EVENTS = """
    SELECT e.slug, e.title, e.starts_at, e.status, e.paused_at IS NOT NULL AS paused, e.ahavah_attending,
           COALESCE((SELECT SUM(v.views) FROM event_view_day v WHERE v.event_id = e.id), 0)::int AS views,
           COUNT(r.id)::int AS rsvps,
           COUNT(r.id) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL)::int AS confirmed,
           COUNT(r.id) FILTER (WHERE r.attended_at IS NOT NULL)::int AS attended,
           (SELECT COUNT(*) FROM person p WHERE p.lead_source = 'event:' || e.slug)::int AS signups,
           COUNT(r.id) FILTER (WHERE r.new_address)::int AS new_addresses,
           COUNT(r.id) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL
                                 AND r.person_id IS NOT NULL)::int AS member_rsvps,
           COUNT(r.id) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL
                                 AND g.name = 'Woman')::int AS women_members
      FROM event e
      LEFT JOIN event_rsvp r ON r.event_id = e.id
      LEFT JOIN person p ON p.id = r.person_id
      LEFT JOIN gender g ON g.id = p.gender_id
     WHERE e.status <> 'draft'
     GROUP BY e.id
     ORDER BY e.starts_at DESC, e.id
"""

_Q_ORGANISERS = """
    SELECT o.id, o.name, o.kind, o.approved_at, o.revoked_at,
           (SELECT COUNT(*) FROM event e WHERE e.organiser_id = o.id AND e.status <> 'draft')::int AS events,
           (SELECT COALESCE(SUM(r.party_size), 0) FROM event_rsvp r JOIN event e ON e.id = r.event_id
             WHERE e.organiser_id = o.id AND r.share_tag = 'host' AND r.status = 'going'
               AND r.confirmed_at IS NOT NULL AND r.erased_at IS NULL)::int AS host_share_guests
      FROM organiser o ORDER BY o.created_at, o.id
"""

# Views and RSVPs by share tag, per gathering (migration 0081; in-app entry
# plan, section 7, measurement). Counts only.
_Q_SHARE_VIEWS = """
    SELECT e.slug, v.share_tag, SUM(v.views)::int AS n
      FROM event_view_share_day v JOIN event e ON e.id = v.event_id
     GROUP BY e.slug, v.share_tag
"""
_Q_SHARE_RSVPS = """
    SELECT e.slug, r.share_tag, COUNT(*)::int AS rsvps,
           COUNT(*) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL)::int AS confirmed
      FROM event_rsvp r JOIN event e ON e.id = r.event_id
     WHERE r.share_tag IS NOT NULL
     GROUP BY e.slug, r.share_tag
"""


def _shares(tx) -> dict[str, dict]:
    """{slug: {tag: {views, rsvps, confirmed}}} for every share tag."""
    from service.events.public import SHARE_TAGS
    out: dict[str, dict] = {}

    def slot(slug: str) -> dict:
        return out.setdefault(slug, {t: dict(views=0, rsvps=0, confirmed=0) for t in SHARE_TAGS})
    for r in tx.execute(_Q_SHARE_VIEWS).fetchall():
        slot(r['slug'])[r['share_tag']]['views'] = r['n']
    for r in tx.execute(_Q_SHARE_RSVPS).fetchall():
        slot(r['slug'])[r['share_tag']].update(rsvps=r['rsvps'], confirmed=r['confirmed'])
    return out


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _rows(tx, q: str, **params) -> list[dict]:
    out = []
    for r in tx.execute(q, params).fetchall():
        out.append({k: _iso(v) if isinstance(v, datetime) else v for k, v in dict(r).items()})
    return out


def overview(tx, now: Optional[datetime] = None) -> dict:
    """Everything the Events tab shows. waiting_count is what needs the
    owner: organisers and gatherings waiting, and new invite requests."""
    from service.events.public import SHARE_TAGS
    waiting = dict(organisers=_rows(tx, _Q_WAITING_ORGANISERS), events=_rows(tx, _Q_WAITING_EVENTS))
    requests = _rows(tx, _Q_REQUESTS)
    shares = _shares(tx)
    none = {t: dict(views=0, rsvps=0, confirmed=0) for t in SHARE_TAGS}
    events = [dict(e, shares=shares.get(e['slug'], none)) for e in _rows(tx, _Q_EVENTS)]
    return dict(waiting=waiting, requests=requests, events=events,
                organisers=_rows(tx, _Q_ORGANISERS),
                waiting_count=(len(waiting['organisers']) + len(waiting['events'])
                               + sum(1 for r in requests if r['status'] == 'new')))


_Q_WEEKS = """
    WITH e AS (SELECT id, slug FROM event WHERE slug = %(slug)s),
    marks AS (
        SELECT date_trunc('week', v.day)::date AS week, v.views AS views, 0 AS rsvps, 0 AS confirmed, 0 AS signups
          FROM event_view_day v JOIN e ON e.id = v.event_id
        UNION ALL
        SELECT date_trunc('week', r.created_at)::date, 0, 1, 0, 0
          FROM event_rsvp r JOIN e ON e.id = r.event_id
        UNION ALL
        SELECT date_trunc('week', r.confirmed_at)::date, 0, 0, 1, 0
          FROM event_rsvp r JOIN e ON e.id = r.event_id WHERE r.confirmed_at IS NOT NULL
        UNION ALL
        SELECT date_trunc('week', p.sign_up_time)::date, 0, 0, 0, 1
          FROM person p JOIN e ON p.lead_source = 'event:' || e.slug
    )
    SELECT week, SUM(views)::int AS views, SUM(rsvps)::int AS rsvps,
           SUM(confirmed)::int AS confirmed, SUM(signups)::int AS signups
      FROM marks GROUP BY week ORDER BY week
"""


def event_weeks(tx, slug: str) -> list[dict]:
    """Per ISO week (its Monday): views, RSVPs made, RSVPs confirmed and
    sign-ups credited to the gathering (admin 3.4). An unknown slug has no
    weeks, as an unknown campaign run has zero counts."""
    return [dict(week=r['week'].isoformat(), views=r['views'], rsvps=r['rsvps'],
                 confirmed=r['confirmed'], signups=r['signups'])
            for r in tx.execute(_Q_WEEKS, dict(slug=slug)).fetchall()]


def _organiser(tx, organiser_id: int) -> dict:
    row = tx.execute('SELECT * FROM organiser WHERE id = %(i)s FOR UPDATE', dict(i=organiser_id)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return dict(row)


def _event(tx, slug: str) -> dict:
    row = tx.execute('SELECT * FROM event WHERE slug = %(s)s FOR UPDATE', dict(s=slug)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return dict(row)


def approve_organiser(tx, admin_person_id: int, organiser_id: int, kind: Optional[str] = None) -> None:
    """Approved once; their next gathering publishes unless flagged. Their
    gatherings already waiting stay waiting (each is approved on its own).
    The organiser is told, with a fresh manage link."""
    from service.events.fields import KINDS
    from service.events.organisers import issue_link
    if kind is not None and kind not in KINDS:
        raise EventError('bad_kind', 400)
    o = _organiser(tx, organiser_id)
    if o['revoked_at'] is not None:
        raise EventError('revoked', 409)
    tx.execute(
        """UPDATE organiser SET approved_at = COALESCE(approved_at, NOW()),
                                approved_by = COALESCE(approved_by, %(a)s),
                                kind = COALESCE(%(k)s, kind)
            WHERE id = %(i)s""", dict(a=admin_person_id, k=kind, i=organiser_id))
    mail.queue_manage_link(tx, organiser_id, issue_link(tx, organiser_id),
                           note=mail.APPROVED_NOTE, subject=mail.APPROVED_SUBJECT)


def _pause_posts(tx, slug: str) -> int:
    """Posts of a paused gathering, cancelled with a reason resume_event
    recognises: growthposts keys a post by its date and a cancelled key
    stays taken, so queueing again would make none."""
    return tx.execute(
        """UPDATE publishing_queue SET status = 'cancelled', error = 'event_paused', updated_at = NOW()
            WHERE kind = 'event' AND request_key LIKE %(p)s
              AND status IN ('awaiting_render', 'review', 'scheduled', 'failed')""",
        dict(p=f'event:{slug}:%')).rowcount


def _restore_posts(tx, slug: str, starts_at: datetime, now: datetime) -> int:
    """The paused posts back to awaiting_render, to be drawn and approved
    again, while their slot is still ahead of the gathering."""
    return tx.execute(
        """UPDATE publishing_queue SET status = 'awaiting_render', error = NULL, updated_at = NOW()
            WHERE kind = 'event' AND request_key LIKE %(p)s
              AND status = 'cancelled' AND error = 'event_paused'
              AND scheduled_for > %(now)s AND scheduled_for < %(start)s""",
        dict(p=f'event:{slug}:%', now=now, start=starts_at)).rowcount


def _pause(tx, event: dict) -> None:
    tx.execute('UPDATE event SET paused_at = COALESCE(paused_at, NOW()), updated_at = NOW() WHERE id = %(i)s',
               dict(i=event['id']))
    _pause_posts(tx, event['slug'])


def revoke_organiser(tx, admin_person_id: int, organiser_id: int) -> None:
    """Their links stop working and every published gathering of theirs is
    paused (plan item 16). No email."""
    _organiser(tx, organiser_id)
    tx.execute('UPDATE organiser SET revoked_at = COALESCE(revoked_at, NOW()) WHERE id = %(i)s',
               dict(i=organiser_id))
    for ev in tx.execute("SELECT * FROM event WHERE organiser_id = %(i)s AND status = 'published' FOR UPDATE",
                         dict(i=organiser_id)).fetchall():
        _pause(tx, dict(ev))


def decline_organiser(tx, admin_person_id: int, organiser_id: int) -> None:
    """Declining a request to host revokes it (plan item 16)."""
    revoke_organiser(tx, admin_person_id, organiser_id)


def create_organiser(tx, admin_person_id: int, *, name: str, email: str, kind: str = 'ahavah') -> dict:
    """Ahavah's own organiser (or another the admin adds): approved now and
    sent the manage link."""
    from service.events import organisers
    row = organisers.create_organiser(tx, name=name, email=email, kind=kind, admin_person_id=admin_person_id)
    mail.queue_manage_link(tx, row['id'], organisers.issue_link(tx, row['id']))
    return row


def approve_event(tx, admin_person_id: int, slug: str, now: Optional[datetime] = None) -> None:
    """A waiting gathering published, its flag cleared, its posts queued
    and its organiser told it is live (with the share kit while it is on
    for them, mail.queue_live)."""
    now = now or datetime.now(timezone.utc)
    ev = _event(tx, slug)
    if ev['status'] != 'pending':
        raise EventError('not_waiting', 409)
    if ev['starts_at'] <= now:
        raise EventError('started', 409)
    manage.publish_now(tx, ev, now)
    manage.send_held_change(tx, ev['id'])
    mail.queue_live(tx, ev['id'])


def decline_event(tx, admin_person_id: int, slug: str) -> None:
    """Back to the organiser's drafts, marked declined. No email."""
    from service.spotlight.growthposts import cancel_event_posts
    ev = _event(tx, slug)
    if ev['status'] not in ('pending', 'published'):
        raise EventError('not_waiting', 409)
    tx.execute("UPDATE event SET status = 'draft', flag_reason = 'declined', updated_at = NOW() WHERE id = %(i)s",
               dict(i=ev['id']))
    cancel_event_posts(tx, slug)


def pause_event(tx, admin_person_id: int, slug: str) -> None:
    """The public can no longer find it and its posts stop. No email."""
    _pause(tx, _event(tx, slug))


def resume_event(tx, admin_person_id: int, slug: str, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(timezone.utc)
    ev = _event(tx, slug)
    organiser = tx.execute('SELECT revoked_at FROM organiser WHERE id = %(i)s',
                           dict(i=ev['organiser_id'])).fetchone()
    if organiser['revoked_at'] is not None:
        raise EventError('revoked', 409)
    tx.execute('UPDATE event SET paused_at = NULL, updated_at = NOW() WHERE id = %(i)s', dict(i=ev['id']))
    if ev['status'] == 'published':
        _restore_posts(tx, slug, ev['starts_at'], now)
        if ev['starts_at'] > now:
            # A date moved while paused has no posts yet; a date that did
            # not move has its keys taken, so this queues nothing more.
            manage._queue_posts(tx, manage._event_by_id(tx, ev['id']), now)
            manage.send_held_change(tx, ev['id'])


def set_attending(tx, admin_person_id: int, slug: str, on: bool) -> None:
    """"Ahavah will be there"."""
    ev = _event(tx, slug)
    tx.execute('UPDATE event SET ahavah_attending = %(on)s, updated_at = NOW() WHERE id = %(i)s',
               dict(on=on is True, i=ev['id']))


def set_request(tx, admin_person_id: int, request_id: int, *, status: Optional[str],
                notes: Optional[str]) -> dict:
    from service.events.fields import clean_text
    if status is not None and status not in INVITE_STATUSES:
        raise EventError('bad_status', 400)
    clean_notes = None
    if notes is not None:
        clean_notes = clean_text(notes, 2000, multiline=True) if notes.strip() else ''
    row = tx.execute(
        """UPDATE ahavah_invite_request
              SET status = COALESCE(%(s)s, status),
                  notes = CASE WHEN %(n)s::text IS NULL THEN notes ELSE NULLIF(%(n)s, '') END,
                  updated_at = NOW()
            WHERE id = %(i)s
        RETURNING id, gathering, dates, place, numbers, contact_name, contact_email, status, notes, created_at""",
        dict(s=status, n=clean_notes, i=request_id)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return {k: _iso(v) if isinstance(v, datetime) else v for k, v in dict(row).items()}
