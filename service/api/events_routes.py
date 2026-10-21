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
    so a new organiser can save drafts at once (export 4.7)."""
    from service.events import EventError, live, organisers, surface_on
    from service.events.fields import clean_text
    if not live() or not surface_on('events_hosting'):
        return _off()
    try:
        name = clean_text(req.name, 80)
        city = _optional(req.city, 80)
        country = _optional(req.country, 80)
        about = None
        if req.about is not None and req.about.strip():
            about = clean_text(req.about, 1000, multiline=True)
        with api_tx() as tx:
            out = organisers.request_host(tx, email=s.email, name=name, kind=req.kind,
                                          city=city, country=country, about=about)
    except EventError as e:
        return _refused(e)
    return out, 201


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
    return dict(organisers.me(o), groups=view['groups']), 200, {'Cache-Control': 'no-store'}


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
    from service.events import manage
    return _organiser_call(
        lambda tx, o: (manage.organiser_preview(tx, o, slug), 200, {'Cache-Control': 'no-store'}))


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
