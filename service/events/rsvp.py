"""RSVP without an account (TEC-1845).

A visitor gives a name, an email and a party size; the place is held only
once they tap the emailed link, which opens the web page, which confirms
by a script call (so a mail scanner opening the link confirms nothing).
A signed-in member is confirmed at once: the address is already proved.

One token per RSVP confirms, shows, cancels and serves the calendar file,
stored only as its sha256. The confirm window is CONFIRM_WINDOW or until
the gathering starts, whichever comes first.

Every confirmed RSVP from a visitor is a lead with the source
event:{slug} (service.leads); a member is never a lead. The unticked box
is the only marketing consent.

Every function takes the caller's transaction and never opens one. The
route that confirms runs read committed, so the lock on the event row
sees the place another guest has just taken.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from service.events import EventError
from service.leads import clean_email, new_token, token_hash
from service.leads.sources import event_source

PARTY_MAX = 10
CONFIRM_WINDOW = timedelta(days=7)
# The key of the wording "Tell me about Ahavah events and members near me".
# A new wording gets a new key.
NEWS_WORDING = 'events-rsvp-news-v1'
# The confirm email goes at most this many times to one unconfirmed RSVP
# (the first and two "Send it again", export 2.7 and 2.9).
SENDS_MAX = 3
# A guest's link shows their RSVP until a day after the gathering ends.
VIEW_AFTER_END = timedelta(days=1)
_TOKEN_MIN, _TOKEN_MAX = 16, 64


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _going_others(tx, event_id: int, rsvp_id: Optional[int]) -> int:
    row = tx.execute(
        """SELECT COALESCE(SUM(party_size), 0)::int AS n FROM event_rsvp
            WHERE event_id = %(e)s AND status = 'going' AND confirmed_at IS NOT NULL
              AND id IS DISTINCT FROM %(r)s""",
        dict(e=event_id, r=rsvp_id)).fetchone()
    return row['n']


def _check_places(event: dict, taken: int, party_size: int) -> None:
    if event['capacity'] is None:
        return
    left = max(event['capacity'] - taken, 0)
    if left == 0:
        raise EventError('full', 409, places_left=0)
    if party_size > left:
        raise EventError('too_many', 409, places_left=left)


def _open_event(tx, slug: str, now: datetime, *, lock: bool) -> dict:
    from service.events.public import _VISIBLE
    row = tx.execute(
        f"SELECT e.* FROM event e WHERE e.slug = %(s)s AND {_VISIBLE}{' FOR UPDATE' if lock else ''}",
        dict(s=slug)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    if row['status'] == 'cancelled' or row['starts_at'] <= now:
        raise EventError('closed', 409)
    return dict(row)


def _clean_name(name: object) -> str:
    from service.events.fields import clean_text
    try:
        return clean_text(name, 80)
    except EventError:
        raise EventError('bad_name', 400)


def rsvp(tx, slug: str, *, name: str, email: Optional[str], party_size: int,
         share_email: bool, news: bool, member, now: Optional[datetime] = None) -> dict:
    """{state: 'check_email', email} for a visitor, {state: 'confirmed',
    token} for a signed-in member."""
    from service.events import mail
    from service.leads import record_lead
    now = _now(now)
    if isinstance(party_size, bool) or not isinstance(party_size, int) or not 1 <= party_size <= PARTY_MAX:
        raise EventError('bad_party', 400)
    name = _clean_name(name)
    if member is not None:
        return _member_rsvp(tx, slug, name=name, party_size=party_size,
                            share_email=share_email, member=member, now=now)
    cleaned = clean_email(email)
    if cleaned is None:
        raise EventError('bad_email', 400)
    address, normalised = cleaned
    event = _open_event(tx, slug, now, lock=False)
    existing = tx.execute(
        """SELECT * FROM event_rsvp WHERE event_id = %(e)s AND normalized_email = %(ne)s FOR UPDATE""",
        dict(e=event['id'], ne=normalised)).fetchone()
    existing = dict(existing) if existing else None
    confirmed = (existing is not None and existing['status'] == 'going'
                 and existing['confirmed_at'] is not None)
    if existing is not None and existing['status'] == 'going' and existing['resends'] + 1 >= SENDS_MAX:
        raise EventError('too_many_tries', 429)
    if not confirmed:
        _check_places(event, _going_others(tx, event['id'], existing and existing['id']), party_size)
    person = tx.execute('SELECT id FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                        dict(ne=normalised)).fetchone()
    new_address = person is None and tx.execute(
        'SELECT 1 FROM lead WHERE normalized_email = %(ne)s LIMIT 1', dict(ne=normalised)).fetchone() is None
    lead_id = record_lead(tx, email=address, source=event_source(slug), marketing_consent=news is True,
                          consent_wording=NEWS_WORDING if news is True else None)
    token, hashed = new_token()
    confirm_by = min(now + CONFIRM_WINDOW, event['starts_at'])
    if existing is None:
        rid = tx.execute(
            """INSERT INTO event_rsvp (event_id, name, email, normalized_email, party_size,
                                       token_hash, confirm_by, share_email_with_organiser,
                                       marketing_consent, source, person_id, lead_id, new_address)
               VALUES (%(e)s, %(n)s, %(a)s, %(ne)s, %(p)s, %(h)s, %(cb)s, %(sh)s, %(mc)s, %(src)s,
                       %(pid)s, %(l)s, %(new)s)
               ON CONFLICT (event_id, normalized_email) DO NOTHING
               RETURNING id""",
            dict(e=event['id'], n=name, a=address, ne=normalised, p=party_size, h=hashed,
                 cb=confirm_by, sh=share_email is True, mc=news is True, src=event_source(slug),
                 pid=person['id'] if person else None, l=lead_id, new=new_address)).fetchone()
        if rid is None:
            raise EventError('try_again', 409)
        rid, resends = rid['id'], 0
    elif confirmed:
        # Already holding a place: a fresh link by email, and nothing else
        # changes until the guest proves the address again.
        rid, resends = existing['id'], existing['resends'] + 1
        tx.execute('UPDATE event_rsvp SET token_hash = %(h)s, resends = %(r)s WHERE id = %(i)s',
                   dict(h=hashed, r=resends, i=rid))
    else:
        rid = existing['id']
        resends = existing['resends'] + 1 if existing['status'] == 'going' else 0
        tx.execute(
            """UPDATE event_rsvp SET name = %(n)s, email = %(a)s, party_size = %(p)s,
                                     token_hash = %(h)s, confirm_by = %(cb)s,
                                     share_email_with_organiser = %(sh)s,
                                     marketing_consent = marketing_consent OR %(mc)s,
                                     status = 'going', confirmed_at = NULL, cancelled_at = NULL,
                                     resends = %(r)s, lead_id = COALESCE(%(l)s, lead_id),
                                     person_id = COALESCE(%(pid)s, person_id)
                WHERE id = %(i)s""",
            dict(n=name, a=address, p=party_size, h=hashed, cb=confirm_by, sh=share_email is True,
                 mc=news is True, r=resends, l=lead_id, pid=person['id'] if person else None, i=rid))
    mail.queue_confirm(tx, rid, token)
    return dict(state='check_email', email=address)


def _member_rsvp(tx, slug: str, *, name: str, party_size: int, share_email: bool, member,
                 now: datetime) -> dict:
    """Confirmed at once, under the event row's lock, as a confirm is."""
    event = _open_event(tx, slug, now, lock=True)
    person = tx.execute('SELECT email, normalized_email FROM person WHERE id = %(i)s',
                        dict(i=member.person_id)).fetchone()
    if person is None:
        raise EventError('not_found', 404)
    existing = tx.execute(
        'SELECT id, status, confirmed_at FROM event_rsvp WHERE event_id = %(e)s AND normalized_email = %(ne)s',
        dict(e=event['id'], ne=person['normalized_email'])).fetchone()
    _check_places(event, _going_others(tx, event['id'], existing and existing['id']), party_size)
    token, hashed = new_token()
    row = tx.execute(
        """INSERT INTO event_rsvp (event_id, name, email, normalized_email, party_size, token_hash,
                                   confirm_by, confirmed_at, share_email_with_organiser, source,
                                   person_id)
           VALUES (%(e)s, %(n)s, %(a)s, %(ne)s, %(p)s, %(h)s, %(now)s, %(now)s, %(sh)s, %(src)s, %(pid)s)
           ON CONFLICT (event_id, normalized_email) DO UPDATE SET
               name = EXCLUDED.name, party_size = EXCLUDED.party_size,
               token_hash = EXCLUDED.token_hash, status = 'going', cancelled_at = NULL,
               confirmed_at = COALESCE(event_rsvp.confirmed_at, EXCLUDED.confirmed_at),
               share_email_with_organiser = EXCLUDED.share_email_with_organiser,
               person_id = EXCLUDED.person_id
           RETURNING id""",
        dict(e=event['id'], n=name, a=person['email'], ne=person['normalized_email'], p=party_size,
             h=hashed, now=now, sh=share_email is True, src=event_source(slug),
             pid=member.person_id)).fetchone()
    return dict(state='confirmed', token=token)


def _by_token(tx, token: object, *, lock: bool = False) -> dict:
    if not isinstance(token, str) or not _TOKEN_MIN <= len(token) <= _TOKEN_MAX:
        raise EventError('not_found', 404)
    row = tx.execute(
        f"SELECT * FROM event_rsvp WHERE token_hash = %(h)s AND erased_at IS NULL{' FOR UPDATE' if lock else ''}",
        dict(h=token_hash(token))).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return dict(row)


def rsvp_view(tx, token: str, now: Optional[datetime] = None) -> dict:
    """{event, rsvp}: the gathering as its page shows it, with the venue
    and the call link once the guest has confirmed."""
    return _view_of_rsvp(tx, _by_token(tx, token), _now(now))


def _view_of_rsvp(tx, r: dict, now: datetime) -> dict:
    """rsvp_view for an RSVP row already read, by its token or by its
    member."""
    from service.events import public
    row = tx.execute('SELECT slug FROM event WHERE id = %(i)s', dict(i=r['event_id'])).fetchone()
    event_row = public.event_row(tx, row['slug'])
    if event_row['ends_at'] + VIEW_AFTER_END <= now:
        raise EventError('not_found', 404)
    event = public.view_of(event_row, now)
    confirmed = r['confirmed_at'] is not None
    # A gathering an admin pulled (paused, or sent back for approval) keeps
    # its venue and call link from everyone, its guests included.
    if not public.visible(event_row):
        event.pop('venue', None)
    elif confirmed and r['status'] == 'going':
        if event_row['mode'] == 'in_person' and event_row['venue']:
            event['venue'] = event_row['venue']
        if event_row['mode'] == 'online':
            event['online_url'] = event_row['online_url']
    return dict(event=event, rsvp=dict(name=r['name'], party_size=r['party_size'],
                                       status=r['status'], confirmed=confirmed))


def confirm(tx, token: str, now: Optional[datetime] = None) -> dict:
    """Takes the place under the event row's lock. Confirming again shows
    the same view. A gathering the public cannot find (paused, or waiting
    for approval) takes no place; one that has started takes none either,
    even when it was moved earlier than the link's window."""
    from service.events.public import visible
    from service.leads import confirm_lead
    now = _now(now)
    r = _by_token(tx, token)
    event = dict(tx.execute('SELECT * FROM event WHERE id = %(i)s FOR UPDATE',
                            dict(i=r['event_id'])).fetchone())
    r = _by_token(tx, token, lock=True)
    if r['confirmed_at'] is not None or r['status'] != 'going':
        return rsvp_view(tx, token, now)
    if event['status'] == 'cancelled':
        raise EventError('cancelled_now', 409)
    if not visible(event):
        raise EventError('not_found', 404)
    if r['confirm_by'] <= now or event['starts_at'] <= now:
        raise EventError('expired', 410)
    try:
        _check_places(event, _going_others(tx, event['id'], r['id']), r['party_size'])
    except EventError:
        raise EventError('full_now', 409)
    tx.execute('UPDATE event_rsvp SET confirmed_at = %(now)s WHERE id = %(i)s', dict(now=now, i=r['id']))
    if r['lead_id'] is not None:
        confirm_lead(tx, r['lead_id'], 'link')
    return rsvp_view(tx, token, now)


def cancel(tx, token: str, now: Optional[datetime] = None) -> dict:
    """The guest gives up their place; it is free at once."""
    r = _by_token(tx, token, lock=True)
    if r['status'] != 'cancelled':
        tx.execute("UPDATE event_rsvp SET status = 'cancelled', cancelled_at = NOW() WHERE id = %(i)s",
                   dict(i=r['id']))
    return rsvp_view(tx, token, now)


# Your gatherings > Going (TEC-1845, in-app entry plan, release 2): how many
# places each list shows. A member has few; the caps keep one answer small.
GOING_UPCOMING_MAX = 50
GOING_PAST_MAX = 20

# The member's own places, by the RSVP's person (set when a member RSVPs,
# and at sign-up by retention.link_rsvps_to_person for places booked
# before joining). Confirmed and not erased, on a gathering the public may
# find (a paused one, or one sent back for approval, is left out until it
# is back). Public fields only: never the venue, the call link or the
# guest's own name and address.
_Q_MEMBER_PLACES = """
    SELECT r.id, r.status, r.party_size, e.slug, e.title, e.starts_at, e.ends_at, e.tz, e.tz_label,
           e.mode, e.city, e.country, e.status AS event_status
      FROM event_rsvp r JOIN event e ON e.id = r.event_id
     WHERE r.person_id = %(pid)s AND r.erased_at IS NULL AND r.confirmed_at IS NOT NULL
       AND {visible} AND {when}
     ORDER BY {order}
     LIMIT %(n)s
"""


def _place(row: dict, now: datetime) -> dict:
    from service.events.public import _iso
    open_ = row['ends_at'] + VIEW_AFTER_END > now
    return dict(
        id=row['id'], state=row['status'], party_size=row['party_size'],
        gathering=dict(slug=row['slug'], title=row['title'], starts_at=_iso(row['starts_at']),
                       ends_at=_iso(row['ends_at']), tz=row['tz'], tz_label=row['tz_label'],
                       mode=row['mode'], city=row['city'], country=row['country'],
                       cancelled=row['event_status'] == 'cancelled'),
        # The member's own view of the place (member_place), while the
        # guest's emailed link would still show it.
        place_path=f"/rsvp/mine/{row['id']}" if open_ else None)


def member_places(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    """{upcoming, past, more_upcoming, more_past}: the member's places.
    Upcoming is every gathering not yet ended, soonest first; past the
    ended ones, most recent first. Each list is capped, and says when
    there is more."""
    from service.events.public import _VISIBLE
    now = _now(now)
    out: dict = {}
    for key, when, order, cap in (
            ('upcoming', 'e.ends_at > %(now)s', 'e.starts_at, r.id', GOING_UPCOMING_MAX),
            ('past', 'e.ends_at <= %(now)s', 'e.starts_at DESC, r.id DESC', GOING_PAST_MAX)):
        rows = tx.execute(_Q_MEMBER_PLACES.format(visible=_VISIBLE, when=when, order=order),
                          dict(pid=person_id, now=now, n=cap + 1)).fetchall()
        out[key] = [_place(dict(r), now) for r in rows[:cap]]
        out[f'more_{key}'] = len(rows) > cap
    return out


def member_place(tx, person_id: int, rsvp_id: int, now: Optional[datetime] = None) -> dict:
    """The member's own view of one of their places: what their emailed
    link shows (rsvp_view), the venue and the call link included once
    confirmed, without the token, which is stored only as its hash. Never
    another person's place."""
    row = tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s AND person_id = %(p)s AND erased_at IS NULL',
                     dict(i=rsvp_id, p=person_id)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return _view_of_rsvp(tx, dict(row), _now(now))


def reissue_token(tx, rsvp_id: int) -> str:
    """A new token for a later email (a change, a cancellation, the
    reminder). It replaces the stored hash, so the earlier link retires."""
    token, hashed = new_token()
    tx.execute('UPDATE event_rsvp SET token_hash = %(h)s WHERE id = %(i)s', dict(h=hashed, i=rsvp_id))
    return token


def calendar(tx, token: str, now: Optional[datetime] = None) -> str:
    """The guest's calendar file: the location only once confirmed."""
    from service.config import WEB_BASE_URL
    from service.events.ics import calendar_file
    now = _now(now)
    view = rsvp_view(tx, token, now)
    r = _by_token(tx, token)
    e = dict(tx.execute('SELECT slug, title, starts_at, ends_at, status, mode, venue, online_url '
                        'FROM event WHERE id = %(i)s', dict(i=r['event_id'])).fetchone())
    # The view holds the venue or the call link only for a confirmed guest
    # of a gathering the public can find.
    ev = view['event']
    location = ev.get('venue') if e['mode'] == 'in_person' else ev.get('online_url')
    if not (view['rsvp']['confirmed'] and view['rsvp']['status'] == 'going'):
        location = None
    return calendar_file(e, location=location, url=f"{WEB_BASE_URL}/e/{e['slug']}", now=now)
