"""In-app notices for the signed-in member (report rewards plan, 3 Nov 2026,
TEC-2025). Sibling module, imported at the bottom of service/api/__init__.py.

  GET  /notices                    the member's undismissed notices, newest first, at most 5
  POST /notices/<id>/seen          stamps seen_at (first time only)
  POST /notices/<id>/dismiss       stamps seen_at if unset, and dismissed_at

A notice that is not the caller's answers 404, the same as one that does not
exist.
"""
from __future__ import annotations

import duotypes as t
from flask import abort

from database import api_tx
from service.api.decorators import aget, apost


@aget('/notices')
def get_notices(s: t.SessionInfo):
    from service import notices
    with api_tx('read committed') as tx:
        return dict(notices=notices.list_open(tx, s.person_id))


@apost('/notices/<int:notice_id>/seen')
def post_notice_seen(s: t.SessionInfo, notice_id: int):
    from service import notices
    with api_tx('read committed') as tx:
        found = notices.mark_seen(tx, s.person_id, notice_id)
    if not found:
        abort(404)
    return dict(ok=True)


@apost('/notices/<int:notice_id>/dismiss')
def post_notice_dismiss(s: t.SessionInfo, notice_id: int):
    from service import notices
    with api_tx('read committed') as tx:
        found = notices.dismiss(tx, s.person_id, notice_id)
    if not found:
        abort(404)
    return dict(ok=True)
