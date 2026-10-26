"""Gatherings, the public and organiser routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as tools_routes is.
RSVPing needs no account. Organisers have no account either: they prove
who they are with the X-Organiser-Token header, the token from their
emailed magic link. Every route but /events/status answers 404 while
events_live is off.
"""
from __future__ import annotations

from typing import Optional

from flask import request

import duotypes as t
from database import api_tx
from service.api.decorators import (
    aget,
    apost,
    app,
    delete,
    get,
    limiter,
    patch,
    post,
    shared_recipient_limit,
    validate,
)


def _off():
    return dict(error='not_found'), 404


# Every path a gathering route lives under. While events_live is off they
# all answer 404 before anything else runs (the body check, the limits, the
# session lookup), so a dark release says nothing about itself. Each route
# checks again, for a call that does not come through a request.
_DARK_PATHS = ('/events', '/e', '/rsvp', '/organiser', '/organisers', '/host-requests',
               '/invite-ahavah')


@app.before_request
def _events_dark():
    path = request.path.rstrip('/') or '/'
    if path == '/events/status':
        return None
    if any(path == p or path.startswith(p + '/') for p in _DARK_PATHS):
        from service.events import live
        if not live():
            return _off()
    return None


def _refused(e):
    return dict(error=e.reason, **e.extra), e.status


def _organiser_token():
    return request.headers.get('X-Organiser-Token') or None


@get('/events/status')
def get_events_status():
    """What the web needs before it shows a gathering surface."""
    from service.events import live, surface_on
    return (dict(live=live(), hosting=surface_on('events_hosting'),
                 list=surface_on('events_list'), invite=surface_on('events_invite')),
            200, {'Cache-Control': 'no-store'})


def _organiser(tx):
    from service.events.organisers import organiser_for
    return organiser_for(tx, _organiser_token())


def _optional(value: Optional[str], max_len: int) -> Optional[str]:
    from service.events.fields import clean_text
    if value is None or not value.strip():
        return None
    return clean_text(value, max_len)


@apost('/host-requests', expected_onboarding_status=None)
@validate(t.PostHostRequest)
def post_host_request(req: t.PostHostRequest, s: t.SessionInfo):
    """The request to host. The web proves the address first with
    /request-otp and /check-otp; the answer carries the organiser's token,
    so a new organiser can save drafts at once (export 4.7).

    From the app (in-app entry plan, section 4, release 3) a member sends
    their own session: no code for their own address. For another address
    (a church or ministry's) the code step's session comes as
    `address_token`, behind app_entries; it proves that address, is used
    for this request only and is then deleted when it holds no account.
    Either way the organiser names the member (migration 0080)."""
    from duohash import sha512

    from service.app_entries import enabled_for
    from service.events import EventError, live, organisers, surface_on
    from service.events.fields import clean_text
    if not live() or not surface_on('events_hosting'):
        return _off()
    member_id = s.person_id
    email = s.email
    address_hash = None
    if req.address_token is not None:
        if member_id is None or not enabled_for(member_id, s.email):
            return _off()
        address_hash = sha512(req.address_token)
        with api_tx('read committed') as tx:
            row = tx.execute(
                """SELECT email FROM duo_session
                    WHERE session_token_hash = %(h)s AND signed_in AND session_expiry > NOW()""",
                dict(h=address_hash)).fetchone()
        if row is None:
            return dict(error='unproven'), 403
        email = row['email']
    try:
        name = clean_text(req.name, 80)
        city = _optional(req.city, 80)
        country = _optional(req.country, 80)
        about = None
        if req.about is not None and req.about.strip():
            about = clean_text(req.about, 1000, multiline=True)
        with api_tx() as tx:
            out = organisers.request_host(tx, email=email, name=name, kind=req.kind,
                                          city=city, country=country, about=about,
                                          member_person_id=member_id)
            if address_hash is not None:
                tx.execute('DELETE FROM duo_session WHERE session_token_hash = %(h)s AND person_id IS NULL',
                           dict(h=address_hash))
    except EventError as e:
        return _refused(e)
    return out, 201


@apost('/organiser/member')
def post_organiser_member(s: t.SessionInfo):
    """Hosting from the app (release 3): every organiser the member's
    session opens, each with a fresh link (as the emailed one) and its
    gatherings, and the member's name and address for the request form.
    Behind hosting and app_entries. A POST: each call issues links."""
    from service.app_entries import enabled_for
    from service.events import live, manage, organisers, surface_on
    if not live() or not surface_on('events_hosting') or not enabled_for(s.person_id, s.email):
        return _off()
    with api_tx() as tx:
        person = tx.execute('SELECT name, email FROM person WHERE id = %(i)s',
                            dict(i=s.person_id)).fetchone()
        held = []
        for o in organisers.member_organisers(tx, s.person_id, person['email'] if person else s.email):
            view = manage.organiser_view(tx, o)
            held.append(dict(organisers.me(o), token=organisers.issue_link(tx, o['id']),
                             groups=view['groups']))
    return (dict(name=(person['name'] if person else '') or '', email=person['email'] if person else s.email,
                 organisers=held), 200, {'Cache-Control': 'no-store'})


_link_ip_limit = limiter.shared_limit('10 per hour', scope='organiser_link')


@post('/organisers/link', limiter=[_link_ip_limit, shared_recipient_limit])
@validate(t.PostOrganiserLink)
def post_organiser_link(req: t.PostOrganiserLink):
    """A new magic link by email. Answers 202 {} whether or not the address
    hosts, and a refused address (the free defences) is silent."""
    from service import leads
    from service.events import live, organisers
    if not live():
        return _off()
    # mail_refusal opens its own read, so it runs before the transaction.
    refusal = leads.mail_refusal(email=req.email, ip=request.remote_addr,
                                 stamp=req.signup_stamp, website=req.website)
    if refusal is None:
        with api_tx() as tx:
            organisers.send_new_link(tx, req.email)
    return {}, 202


@get('/organiser/me')
def get_organiser_me():
    from service.events import EventError, live, manage, organisers
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            o = _organiser(tx)
            view = manage.organiser_view(tx, o)
    except EventError as e:
        return _refused(e)
    # kit: whether the organiser pages offer the share kit (round 2, screen 9).
    return (dict(organisers.me(o), groups=view['groups'], kit=organisers.kit_on(o)), 200,
            {'Cache-Control': 'no-store'})


# ---------------------------------------------------------------------------
# An organiser's gatherings. Another organiser's slug answers 404.
# ---------------------------------------------------------------------------

def _organiser_call(fn):
    """Runs fn(tx, organiser) for the token's organiser, answering 404
    while dark and the refusal's status otherwise."""
    from service.events import EventError, live
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            return fn(tx, _organiser(tx))
    except EventError as e:
        return _refused(e)


def _draft(req: t.EventDraftBody) -> dict:
    return req.model_dump(exclude_unset=True)


@post('/organiser/events')
@validate(t.EventDraftBody)
def post_organiser_event(req: t.EventDraftBody):
    from service.events import manage
    return _organiser_call(lambda tx, o: (manage.create_event(tx, o, _draft(req)), 201))


@patch('/organiser/events/<slug>')
@validate(t.EventDraftBody)
def patch_organiser_event(req: t.EventDraftBody, slug: str):
    from service.events import manage
    return _organiser_call(lambda tx, o: manage.update_event(tx, o, slug, _draft(req)))


@post('/organiser/events/<slug>/publish')
def post_organiser_event_publish(slug: str):
    from service.events import manage
    return _organiser_call(lambda tx, o: manage.publish(tx, o, slug))


@post('/organiser/events/<slug>/cancel')
@validate(t.PostEventCancel)
def post_organiser_event_cancel(req: t.PostEventCancel, slug: str):
    from service.events import manage
    return _organiser_call(lambda tx, o: manage.cancel_event(tx, o, slug, req.note))


@get('/organiser/events/<slug>')
def get_organiser_event(slug: str):
    """The organiser's own view of one gathering, and `kit`: whether the
    share kit is offered to them (round 2, screen 9)."""
    from service.events import manage, organisers
    return _organiser_call(
        lambda tx, o: (dict(manage.organiser_preview(tx, o, slug), kit=organisers.kit_on(o)), 200,
                       {'Cache-Control': 'no-store'}))


@get('/organiser/events/<slug>/rsvps')
def get_organiser_event_rsvps(slug: str):
    from service.events import manage
    return _organiser_call(
        lambda tx, o: (manage.rsvp_list(tx, o, slug), 200, {'Cache-Control': 'no-store'}))


@post('/organiser/events/<slug>/rsvps/<int:rid>/attended')
@validate(t.PostAttended)
def post_organiser_rsvp_attended(req: t.PostAttended, slug: str, rid: int):
    from service.events import manage

    def mark(tx, o):
        manage.mark_attended(tx, o, slug, rid, req.attended)
        return '', 204
    return _organiser_call(mark)


@post('/organiser/events/<slug>/cover')
@validate(t.PostEventCover)
def post_organiser_event_cover(req: t.PostEventCover, slug: str):
    import base64
    import binascii

    from service.events import EventError, manage
    try:
        data = base64.b64decode(req.image, validate=True)
    except (binascii.Error, ValueError):
        return _refused(EventError('bad_image', 400))
    return _organiser_call(lambda tx, o: manage.set_cover(tx, o, slug, data, req.content_type))


@delete('/organiser/events/<slug>/cover')
def delete_organiser_event_cover(slug: str):
    from service.events import manage

    def remove(tx, o):
        manage.remove_cover(tx, o, slug)
        return '', 204
    return _organiser_call(remove)


# ---------------------------------------------------------------------------
# The public read
# ---------------------------------------------------------------------------

@get('/events')
def get_events():
    from service.events import EventError, live, public, surface_on
    if not live() or not surface_on('events_list'):
        return _off()
    region = request.args.get('region') or None
    try:
        limit = int(request.args.get('limit') or 20)
    except ValueError:
        limit = 20
    try:
        with api_tx('read committed') as tx:
            events = public.list_events(tx, region=region, limit=limit)
    except EventError as e:
        return _refused(e)
    return dict(events=events), 200, {'Cache-Control': 'public, max-age=60'}


@get('/events/countries')
def get_event_countries():
    from service.events import fields, live
    if not live():
        return _off()
    return dict(countries=fields.countries()), 200, {'Cache-Control': 'public, max-age=86400'}


@get('/events/<slug>')
def get_event(slug: str):
    from service.events import EventError, live, public
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            view = public.event_view(tx, slug)
    except EventError as e:
        return dict(error=e.reason), e.status, {'Cache-Control': 'no-store'}
    return view, 200, {'Cache-Control': 'no-store'}


_view_limit = limiter.shared_limit('60 per hour', scope='event_view')
_NOT_A_READER = ('bot', 'crawler', 'spider', 'preview')


@post('/events/<slug>/view', limiter=_view_limit)
def post_event_view(slug: str):
    """The page's beacon, once per browser tab session. Link previews and
    crawlers are not counted."""
    from datetime import datetime, timezone

    from service.events import live, public
    if not live():
        return _off()
    agent = (request.headers.get('User-Agent') or '').lower()
    if not any(word in agent for word in _NOT_A_READER):
        with api_tx() as tx:
            public.count_view(tx, slug, datetime.now(timezone.utc).date())
    return '', 204


# ---------------------------------------------------------------------------
# RSVPs. Every answer is no-store: each carries one guest's state.
# ---------------------------------------------------------------------------

_NO_STORE = {'Cache-Control': 'no-store'}
_rsvp_ip_limit = limiter.shared_limit('10 per hour; 30 per day', scope='event_rsvp')


@apost('/events/<slug>/rsvp', auth='optional', expected_onboarding_status=None,
       limiter=[_rsvp_ip_limit, shared_recipient_limit])
@validate(t.PostEventRsvp)
def post_event_rsvp(req: t.PostEventRsvp, s: Optional[t.SessionInfo], slug: str):
    """A visitor is asked to check their email; a signed-in member is
    confirmed at once. A refused address (the free defences) gets the same
    answer as a sent one, and nothing is written."""
    from service import leads, signupguard
    from service.events import EventError, live, rsvp
    if not live():
        return _off()
    member = s if s is not None and s.person_id is not None else None
    if member is None:
        cleaned = leads.clean_email(req.email)
        if cleaned is None:
            return dict(error='bad_email'), 400, _NO_STORE
        # mail_refusal opens its own read, so it runs before the transaction.
        refusal = leads.mail_refusal(email=cleaned[0], ip=request.remote_addr,
                                     stamp=req.signup_stamp, website=req.website)
        if refusal:
            signupguard.record_refusal(refusal, new_address=True, email=cleaned[0],
                                       ip=request.remote_addr)
            return dict(state='check_email', email=cleaned[0]), 201, _NO_STORE
    try:
        with api_tx() as tx:
            out = rsvp.rsvp(tx, slug, name=req.name, email=req.email, party_size=req.party_size,
                            share_email=req.share_email, news=req.news, member=member)
    except EventError as e:
        return dict(error=e.reason, **e.extra), e.status, _NO_STORE
    return out, 201, _NO_STORE


@aget('/rsvp/me')
def get_rsvp_me(s: t.SessionInfo):
    """The member's first name and address, for the RSVP form (export 2.3)."""
    from service.events import live
    if not live():
        return _off()
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT name, email FROM person WHERE id = %(i)s',
                         dict(i=s.person_id)).fetchone()
    first = (row['name'] or '').split()[0] if row and row['name'] else ''
    return dict(name=first, email=row['email'] if row else s.email), 200, _NO_STORE


def _member_entries(s: t.SessionInfo) -> bool:
    """A new in-app entry: events_live and app_entries for this member."""
    from service.app_entries import enabled_for
    from service.events import live
    return live() and enabled_for(s.person_id, s.email)


_ICS_HEADERS = {'Content-Type': 'text/calendar; charset=utf-8',
                'Content-Disposition': 'attachment; filename="gathering.ics"',
                'Cache-Control': 'no-store'}


@aget('/rsvp/mine')
def get_rsvp_mine(s: t.SessionInfo):
    """Your gatherings > Going (in-app entry plan, release 2): the member's
    own places, upcoming and past."""
    from service.events import rsvp
    if not _member_entries(s):
        return _off()
    with api_tx('read committed') as tx:
        return rsvp.member_places(tx, s.person_id), 200, _NO_STORE


@aget('/rsvp/mine/<int:rsvp_id>')
def get_rsvp_mine_one(s: t.SessionInfo, rsvp_id: int):
    """The member's own view of one place, as their emailed link shows it."""
    from service.events import EventError, rsvp
    if not _member_entries(s):
        return _off()
    try:
        with api_tx('read committed') as tx:
            return rsvp.member_place(tx, s.person_id, rsvp_id), 200, _NO_STORE
    except EventError as e:
        return dict(error=e.reason, **e.extra), e.status, _NO_STORE


@apost('/rsvp/mine/<int:rsvp_id>/cancel')
def post_rsvp_mine_cancel(s: t.SessionInfo, rsvp_id: int):
    """Cancel my place from the app (in-app entry design 4.7), without the
    emailed link's token."""
    from service.events import EventError, rsvp
    if not _member_entries(s):
        return _off()
    try:
        with api_tx('read committed') as tx:
            return rsvp.member_cancel(tx, s.person_id, rsvp_id), 200, _NO_STORE
    except EventError as e:
        return dict(error=e.reason, **e.extra), e.status, _NO_STORE


@aget('/rsvp/mine/<int:rsvp_id>/calendar.ics')
def get_rsvp_mine_calendar(s: t.SessionInfo, rsvp_id: int):
    """Add to calendar from the app: the emailed link's calendar file."""
    from service.events import EventError, rsvp
    if not _member_entries(s):
        return _off()
    try:
        with api_tx('read committed') as tx:
            body = rsvp.member_calendar(tx, s.person_id, rsvp_id)
    except EventError as e:
        return dict(error=e.reason), e.status, _NO_STORE
    return body, 200, _ICS_HEADERS


def _rsvp_call(fn, isolation: str = 'REPEATABLE READ'):
    from service.events import EventError, live
    if not live():
        return _off()
    try:
        with api_tx(isolation) as tx:
            return fn(tx), 200, _NO_STORE
    except EventError as e:
        return dict(error=e.reason, **e.extra), e.status, _NO_STORE


@get('/rsvp/confirm/<token>')
def get_rsvp_confirm(token: str):
    """Called by the web page's script; no email links here, so a mail
    scanner opening the emailed link confirms nothing. Read committed: the
    lock on the event row must see a place another guest has just taken."""
    from service.events import rsvp
    return _rsvp_call(lambda tx: rsvp.confirm(tx, token), 'read committed')


@get('/rsvp/<token>')
def get_rsvp(token: str):
    from service.events import rsvp
    return _rsvp_call(lambda tx: rsvp.rsvp_view(tx, token))


@post('/rsvp/<token>/cancel')
def post_rsvp_cancel(token: str):
    from service.events import rsvp
    return _rsvp_call(lambda tx: rsvp.cancel(tx, token))


@get('/rsvp/<token>/calendar.ics')
def get_rsvp_calendar(token: str):
    from service.events import EventError, live, rsvp
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            body = rsvp.calendar(tx, token)
    except EventError as e:
        return dict(error=e.reason), e.status, _NO_STORE
    return body, 200, _ICS_HEADERS


# ---------------------------------------------------------------------------
# "Invite Ahavah": leaders ask Ahavah to come. No email; it waits in the admin.
# ---------------------------------------------------------------------------

_invite_limit = limiter.shared_limit('5 per hour', scope='invite_ahavah')


@post('/invite-ahavah', limiter=_invite_limit)
@validate(t.PostInviteAhavah)
def post_invite_ahavah(req: t.PostInviteAhavah):
    from service.events import EventError, invites, live, surface_on
    if not live() or not surface_on('events_invite'):
        return _off()
    if req.website:
        return {}, 201
    try:
        with api_tx() as tx:
            invites.record_request(tx, req.model_dump())
    except EventError as e:
        return _refused(e)
    return {}, 201
