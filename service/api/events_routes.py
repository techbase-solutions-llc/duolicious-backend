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
    get,
    limiter,
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
    from service.events import EventError, live, organisers
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            return organisers.me(_organiser(tx)), 200, {'Cache-Control': 'no-store'}
    except EventError as e:
        return _refused(e)
