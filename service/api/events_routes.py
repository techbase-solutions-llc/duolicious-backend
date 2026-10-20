"""Gatherings, the public and organiser routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as tools_routes is.
RSVPing needs no account. Organisers have no account either: they prove
who they are with the X-Organiser-Token header, the token from their
emailed magic link. Every route but /events/status answers 404 while
events_live is off.
"""
from __future__ import annotations

from flask import request

from service.api.decorators import get


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
