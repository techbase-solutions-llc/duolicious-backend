"""Organisers manage their gatherings (TEC-1845): create, edit, publish,
cancel, their lists, the RSVP list and attendance, and the posts a
published gathering feeds to the scheduler (service/spotlight/growthposts.py).

Every function takes the organiser dict organiser_for returns, so another
organiser's slug is simply not found. Every function takes the caller's
transaction and never opens one.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import psycopg

from service.events import EventError
from service.events import fields as f

# The fields an organiser sets, in the order the draft has them.
DRAFT_FIELDS = ('title', 'starts_at', 'ends_at', 'tz', 'tz_label', 'mode', 'city', 'country',
                'region', 'venue', 'venue_visibility', 'online_url', 'description', 'capacity',
                'tags', 'feast', 'show_going')
# A change to any of these on a published gathering is a change its
# confirmed guests hear about.
GUEST_FACTS = ('starts_at', 'ends_at', 'tz', 'mode', 'city', 'country', 'venue', 'online_url')

_Q_EVENT = """
    SELECT e.*, o.name AS organiser_name, o.kind AS organiser_kind
      FROM event e JOIN organiser o ON o.id = e.organiser_id
     WHERE e.slug = %(slug)s AND e.organiser_id = %(oid)s
"""


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _event(tx, organiser: dict, slug: str, *, lock: bool = False) -> dict:
    """The organiser's own gathering, locked when asked; anyone else's is
    not found."""
    if lock:
        tx.execute('SELECT 1 FROM event WHERE slug = %(slug)s AND organiser_id = %(oid)s FOR UPDATE',
                   dict(slug=slug, oid=organiser['id']))
    row = tx.execute(_Q_EVENT, dict(slug=slug, oid=organiser['id'])).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return dict(row)


def _event_by_id(tx, event_id: int) -> dict:
    return dict(tx.execute(
        """SELECT e.*, o.name AS organiser_name, o.kind AS organiser_kind
             FROM event e JOIN organiser o ON o.id = e.organiser_id WHERE e.id = %(i)s""",
        dict(i=event_id)).fetchone())


def place_words(event: dict, *, confirmed: bool = False) -> str:
    """Where the gathering is, as the public sees it: the venue when the
    organiser made it public (or for a confirmed guest), else the city;
    'Online' for an online one."""
    if event['mode'] == 'online':
        return 'Online'
    if event.get('venue') and (confirmed or event.get('venue_visibility') == 'public'):
        return event['venue']
    return event['city']


def facts(event: dict) -> dict:
    """{date, time, place, venue} for a change's before and after. `place`
    is safe for the public page; `venue` is for the confirmed guests' email
    only and never leaves the API in a public response."""
    date, time = f.when_words(event['starts_at'], event['ends_at'], event['tz'], event['tz_label'])
    return dict(date=date, time=time, place=place_words(event),
                venue=event.get('venue') if event['mode'] == 'in_person' else None,
                mode=event['mode'])


def post_caption(event: dict) -> str:
    """The caption the owner approves with each post. NEW LINE (plan item 12, 25)."""
    date, _ = f.when_words(event['starts_at'], event['ends_at'], event['tz'], event['tz_label'])
    place = event['city'] if event['mode'] == 'in_person' else 'Online'
    return f"{event['title']}. {date}, {place}. Hosted by {event['organiser_name']}."


def post_payload(event: dict) -> dict:
    """The slots of the social set's event card (4.1). Never the venue."""
    date, _ = f.when_words(event['starts_at'], event['ends_at'], event['tz'], event['tz_label'])
    return dict(
        slug=event['slug'], event_title=event['title'], date=date,
        city_or_online=event['city'] if event['mode'] == 'in_person' else 'Online',
        organiser_name=event['organiser_name'],
        tags=[f.TAG_LABELS[t] for t in event['tags'] if t in f.TAG_LABELS],
        feast_label=f.FEASTS.get(event['feast']) if event.get('feast') else None,
        ahavah_attending=bool(event['ahavah_attending']))


def _queue_posts(tx, event: dict, now: datetime) -> list[str]:
    from service.spotlight.growthposts import queue_event_posts
    return queue_event_posts(tx, slug=event['slug'], starts_at=event['starts_at'],
                             caption=post_caption(event), payload=post_payload(event),
                             created_by='events', now=now)


def _cancel_posts(tx, slug: str) -> int:
    from service.spotlight.growthposts import cancel_event_posts
    return cancel_event_posts(tx, slug)


def create_event(tx, organiser: dict, raw: dict) -> dict:
    """A new draft. The slug is fixed now and never changes."""
    d = f.clean_draft(raw)
    cols = [k for k in DRAFT_FIELDS if k in d]
    for _ in range(5):
        slug = f.slug_for(d['title'])
        tx.execute('SAVEPOINT create_event')
        try:
            row = tx.execute(
                f"""INSERT INTO event (slug, organiser_id, ahavah_attending, {', '.join(cols)})
                    VALUES (%(slug)s, %(oid)s, %(ahavah)s, {', '.join(f'%({c})s' for c in cols)})
                    RETURNING slug""",
                dict(d, slug=slug, oid=organiser['id'],
                     ahavah=organiser.get('kind') == 'ahavah')).fetchone()
        except psycopg.errors.UniqueViolation:
            tx.execute('ROLLBACK TO SAVEPOINT create_event')
            continue
        tx.execute('RELEASE SAVEPOINT create_event')
        return dict(slug=row['slug'])
    raise EventError('try_again', 409)


def _stored_draft(row: dict) -> dict:
    return {k: row[k] for k in DRAFT_FIELDS if k != 'region'}


def update_event(tx, organiser: dict, slug: str, raw: dict, now: Optional[datetime] = None) -> dict:
    """An edit. On a published gathering a change to its time, zone, mode or
    place is recorded (before and after) and its confirmed guests are told
    once; a new date cancels its posts and queues new ones. New text the
    filters catch sends it back for approval."""
    from service.events import mail
    now = _now(now)
    row = _event(tx, organiser, slug, lock=True)
    if row['status'] == 'cancelled':
        raise EventError('cancelled', 409)
    f.clean_draft(raw, partial=True)
    d = f.clean_draft({**_stored_draft(row), **raw})
    changed = [k for k in DRAFT_FIELDS if k in d and d[k] != row[k]]
    if not changed:
        return dict(event=dict(slug=slug, status=row['status']), notified=0)
    after = {**row, **d}
    sets = {k: d[k] for k in changed}
    notified = 0
    status = row['status']
    text_changed = any(k in changed for k in ('title', 'description'))
    flag = f.text_flag(d['title'], d['description']) if text_changed else None
    if status == 'published' and flag:
        sets.update(status='pending', flag_reason=flag)
        status = 'pending'
        _cancel_posts(tx, slug)
    moved_facts = [k for k in GUEST_FACTS if k in changed]
    if row['status'] == 'published' and moved_facts:
        sets.update(changed_at=now, change_before=json.dumps(facts(row)),
                    change_after=json.dumps(facts(after)))
    assignments = ', '.join(
        f'{k} = %({k})s::jsonb' if k in ('change_before', 'change_after') else f'{k} = %({k})s'
        for k in sets)
    tx.execute(f'UPDATE event SET {assignments}, updated_at = NOW() WHERE id = %(id)s',
               dict(sets, id=row['id']))
    if row['status'] == 'published' and moved_facts:
        notified = mail.queue_change(tx, row['id'])
    if status == 'published' and 'starts_at' in changed:
        from service.spotlight.growthposts import event_request_key
        if event_request_key(slug, row['starts_at'], 10) != event_request_key(slug, d['starts_at'], 10):
            _cancel_posts(tx, slug)
            _queue_posts(tx, _event_by_id(tx, row['id']), now)
    return dict(event=dict(slug=slug, status=status), notified=notified)


def publish_now(tx, event: dict, now: datetime) -> None:
    """Published, its flag cleared and its posts queued. The organiser's
    publish and the admin's approval both end here."""
    tx.execute(
        """UPDATE event SET status = 'published', flag_reason = NULL,
                            published_at = COALESCE(published_at, %(now)s), updated_at = NOW()
            WHERE id = %(id)s""",
        dict(id=event['id'], now=now))
    _queue_posts(tx, _event_by_id(tx, event['id']), now)


def publish(tx, organiser: dict, slug: str, now: Optional[datetime] = None) -> dict:
    """Published at once when the organiser is approved and nothing is
    flagged; otherwise it waits for an admin with the reason."""
    now = _now(now)
    row = _event(tx, organiser, slug, lock=True)
    if row['status'] in ('published', 'pending'):
        return dict(status=row['status'])
    if row['status'] == 'cancelled':
        raise EventError('cancelled', 409)
    if row['starts_at'] <= now:
        raise EventError('started', 409)
    reason = (f.text_flag(row['title'], row['description']) or row['flag_reason']
              or (None if organiser.get('approved') else 'new_organiser'))
    if reason:
        tx.execute("UPDATE event SET status = 'pending', flag_reason = %(r)s, updated_at = NOW() "
                   "WHERE id = %(id)s", dict(r=reason, id=row['id']))
        return dict(status='pending')
    publish_now(tx, row, now)
    return dict(status='published')


def cancel_event(tx, organiser: dict, slug: str, note: Optional[str]) -> dict:
    """Cancelled, with the organiser's note to the guests. A note the
    filters catch is dropped and its flag kept for the admin; the
    cancellation still goes."""
    from service.events import mail
    row = _event(tx, organiser, slug, lock=True)
    if row['status'] == 'cancelled':
        return dict(notified=0)
    clean = None
    if note is not None and note.strip():
        clean = f.clean_text(note, 500, multiline=True)
    flag = f.text_flag(clean) if clean else None
    if flag:
        clean = None
    was_published = row['status'] == 'published'
    tx.execute(
        """UPDATE event SET status = 'cancelled', cancelled_at = NOW(), cancel_note = %(n)s,
                            flag_reason = COALESCE(%(fl)s, flag_reason), updated_at = NOW()
            WHERE id = %(id)s""",
        dict(n=clean, fl=flag, id=row['id']))
    _cancel_posts(tx, slug)
    notified = mail.queue_cancelled(tx, row['id']) if was_published else 0
    return dict(notified=notified)


_Q_LIST = """
    SELECT e.slug, e.title, e.starts_at, e.ends_at, e.status, e.paused_at IS NOT NULL AS paused,
           COALESCE(SUM(r.party_size) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL), 0)::int AS going,
           COUNT(r.id) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL)::int AS confirmed
      FROM event e LEFT JOIN event_rsvp r ON r.event_id = e.id
     WHERE e.organiser_id = %(oid)s
     GROUP BY e.id
     ORDER BY e.starts_at, e.id
"""


def organiser_view(tx, organiser: dict, now: Optional[datetime] = None) -> dict:
    """"Your gatherings" (export 4.6). `going` counts people (confirmed
    parties), `confirmed` the confirmed RSVPs."""
    from service.events.organisers import me
    now = _now(now)
    groups: dict[str, list] = dict(drafts=[], waiting=[], published=[], cancelled=[], ended=[])
    for r in tx.execute(_Q_LIST, dict(oid=organiser['id'])).fetchall():
        item = dict(slug=r['slug'], title=r['title'], starts_at=r['starts_at'].isoformat(),
                    status=r['status'], paused=r['paused'], going=r['going'],
                    confirmed=r['confirmed'])
        if r['status'] == 'draft':
            groups['drafts'].append(item)
        elif r['status'] == 'pending':
            groups['waiting'].append(item)
        elif r['status'] == 'cancelled':
            groups['cancelled'].append(item)
        elif r['ends_at'] <= now:
            groups['ended'].append(item)
        else:
            groups['published'].append(item)
    return dict(organiser=me(organiser), groups=groups)


def rsvp_list(tx, organiser: dict, slug: str, now: Optional[datetime] = None) -> dict:
    """Names and party sizes (export 4.23); an email only where the guest
    ticked "share my email with the organiser"."""
    now = _now(now)
    event = _event(tx, organiser, slug)
    rows = tx.execute(
        """SELECT id, name, email, party_size, confirmed_at, attended_at,
                  share_email_with_organiser AS share
             FROM event_rsvp
            WHERE event_id = %(e)s AND status = 'going' AND erased_at IS NULL
            ORDER BY created_at, id""",
        dict(e=event['id'])).fetchall()
    going, waiting = [], []
    for r in rows:
        if r['confirmed_at'] is None:
            waiting.append(dict(id=r['id'], name=r['name'], party_size=r['party_size']))
            continue
        g = dict(id=r['id'], name=r['name'], party_size=r['party_size'],
                 attended=r['attended_at'] is not None)
        if r['share']:
            g['email'] = r['email']
        going.append(g)
    return dict(going=going, waiting=waiting,
                total_going=sum(g['party_size'] for g in going),
                can_mark=event['starts_at'] <= now)


def mark_attended(tx, organiser: dict, slug: str, rsvp_id: int, attended: bool,
                  now: Optional[datetime] = None) -> None:
    now = _now(now)
    event = _event(tx, organiser, slug)
    if event['starts_at'] > now:
        raise EventError('not_started', 409)
    n = tx.execute(
        """UPDATE event_rsvp SET attended_at = CASE WHEN %(a)s::boolean THEN COALESCE(attended_at, NOW()) END
            WHERE id = %(r)s AND event_id = %(e)s AND confirmed_at IS NOT NULL""",
        dict(a=attended, r=rsvp_id, e=event['id'])).rowcount
    if n == 0:
        raise EventError('not_found', 404)


def _draft_json(row: dict) -> dict:
    out = {k: row[k] for k in DRAFT_FIELDS}
    out['starts_at'] = row['starts_at'].isoformat()
    out['ends_at'] = row['ends_at'].isoformat()
    return out


def organiser_preview(tx, organiser: dict, slug: str, now: Optional[datetime] = None) -> dict:
    """The organiser's own gathering in any state (export 1.12): the fields
    for the form, its state and preview: True."""
    row = _event(tx, organiser, slug)
    return dict(_draft_json(row), slug=slug, status=row['status'],
                paused=row['paused_at'] is not None, flag_reason=row['flag_reason'],
                preview=True)


# ---------------------------------------------------------------------------
# The cover (plan Task 6)
# ---------------------------------------------------------------------------

COVER_SIZE = (1200, 630)
COVER_MAX_BYTES = 10 * 1024 * 1024
COVER_TYPES = {'image/jpeg': 'JPEG', 'image/png': 'PNG'}
COVER_PREFIX = 'event-covers/'


def cover_url(key: Optional[str]) -> Optional[str]:
    from service.config import USER_IMAGES_BASE_URL
    return f'{USER_IMAGES_BASE_URL}/{key}' if key else None


def _cover_jpeg(data: bytes, content_type: str) -> bytes:
    """A decodable JPEG or PNG under 10 MB, re-encoded to a 1200 by 630
    JPEG, centre-cropped, turned upright and with its EXIF dropped."""
    import io

    from PIL import Image, ImageOps
    if (content_type not in COVER_TYPES or not isinstance(data, (bytes, bytearray))
            or not data or len(data) > COVER_MAX_BYTES):
        raise EventError('bad_image', 400)
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in COVER_TYPES.values():
            raise EventError('bad_image', 400)
        img.load()
        img = ImageOps.exif_transpose(img)
        out = io.BytesIO()
        ImageOps.fit(img.convert('RGB'), COVER_SIZE).save(out, 'JPEG', quality=85)
    except EventError:
        raise
    except Exception:
        raise EventError('bad_image', 400)
    return out.getvalue()


def _delete_cover(key: Optional[str]) -> None:
    """Best effort: a stray object costs a little storage, never a page."""
    if not key:
        return
    from service.spotlight import storage
    try:
        storage._bucket().delete_objects(Delete={'Objects': [{'Key': key}]})
    except Exception as e:
        print(f'events.manage: could not delete cover {key}: {e!r}')


def set_cover(tx, organiser: dict, slug: str, data: bytes, content_type: str) -> dict:
    """Checks, crops and stores the cover. A rejected image is refused and
    nothing is stored; one sent to manual review is kept but sends the
    gathering for approval (flag 'cover_review'). The object is uploaded
    before the key is written, and the old one deleted afterwards."""
    import uuid

    import service.photo_moderation as moderation
    from service.spotlight import storage
    row = _event(tx, organiser, slug, lock=True)
    if row['status'] == 'cancelled':
        raise EventError('cancelled', 409)
    jpeg = _cover_jpeg(data, content_type)
    verdict = moderation.moderate_image_bytes(jpeg)
    if verdict.status == 'rejected':
        raise EventError('bad_image', 400)
    key = f'{COVER_PREFIX}{uuid.uuid4()}.jpg'
    storage._bucket().put_object(Key=key, Body=jpeg, ACL='public-read', ContentType='image/jpeg')
    review = verdict.status != 'approved'
    sets = dict(cover_key=key)
    if review:
        sets['flag_reason'] = 'cover_review'
        if row['status'] == 'published':
            sets['status'] = 'pending'
            _cancel_posts(tx, slug)
    elif row['flag_reason'] == 'cover_review':
        sets['flag_reason'] = None
    tx.execute(f"UPDATE event SET {', '.join(f'{k} = %({k})s' for k in sets)}, updated_at = NOW() "
               "WHERE id = %(id)s", dict(sets, id=row['id']))
    _delete_cover(row['cover_key'])
    return dict(cover_url=cover_url(key))


def remove_cover(tx, organiser: dict, slug: str) -> None:
    row = _event(tx, organiser, slug, lock=True)
    tx.execute(
        """UPDATE event SET cover_key = NULL, updated_at = NOW(),
                            flag_reason = CASE WHEN flag_reason = 'cover_review' THEN NULL ELSE flag_reason END
            WHERE id = %(id)s""", dict(id=row['id']))
    _delete_cover(row['cover_key'])
