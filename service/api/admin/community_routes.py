"""Acting on the community (TEC-1897): who is waiting on a reply, unfinished
sign-ups and the weekly funnel. Admin role only; counts per member, never
content, never who liked whom."""
from __future__ import annotations

import duotypes as t

from database import api_tx
from service.admin import require_admin
from service.admin.jsonrow import iso_row
from service.admin.queries import community
from service.api.decorators import aget
from service.growth.queries import _excluded


@aget('/admin/community/waiting')
def get_admin_community_waiting(s: t.SessionInfo):
    require_admin(s)
    params = dict(ex=_excluded())
    with api_tx('read committed') as tx:
        summary = tx.execute(community.Q_WAITING_SUMMARY, params).fetchone()
        members = tx.execute(community.Q_WAITING_MEMBERS, params).fetchall()
    return dict(summary=iso_row(summary), members=[iso_row(r) for r in members])
