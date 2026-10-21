"""Matchmaker, the member and visitor routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as events_routes is.
Every route but /matchmaker/status answers 404 while matchmaker_live is
off; each surface's routes answer 404 until its own switch is on too.
The mentor's routes live in service/api/mentor_routes.py, the admin's in
service/api/admin/matchmaker_routes.py.
"""
from __future__ import annotations

import re

from flask import request

from service.api.decorators import app, get

_NO_STORE = {'Cache-Control': 'no-store'}


def _off():
    return dict(error='not_found'), 404


def _refused(e):
    return dict(error=e.reason, **e.extra), e.status, _NO_STORE


# Every path a matchmaker route lives under. While matchmaker_live is off
# they all answer 404 before anything else runs (the body check, the
# limits, the session lookup), so a dark release says nothing about itself.
# Each route checks again, for a call that does not come through a request.
_DARK_PATHS = ('/matchmaker', '/alerts', '/introductions', '/recommendations', '/mentor')
_DARK_PATTERNS = (re.compile(r'^/conversations/[^/]+/(share|sharing)$'),
                  re.compile(r'^/matches/[^/]+/mentor-note$'))


@app.before_request
def _matchmaker_dark():
    path = request.path.rstrip('/') or '/'
    if path == '/matchmaker/status':
        return None
    dark = (any(path == p or path.startswith(p + '/') for p in _DARK_PATHS)
            or any(r.match(path) for r in _DARK_PATTERNS))
    if dark:
        from service.matchmaker import live
        if not live():
            return _off()
    return None


@get('/matchmaker/status')
def get_matchmaker_status():
    """What the web needs before it shows a matchmaker surface."""
    from service.matchmaker import live, surface_on
    return (dict(live=live(), alerts=surface_on('matchmaker_alerts'),
                 visitor_alerts=surface_on('matchmaker_visitor_alerts'),
                 introductions=surface_on('matchmaker_introductions'),
                 mentors=surface_on('matchmaker_mentors')),
            200, _NO_STORE)
