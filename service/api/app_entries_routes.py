"""The app_entries switch, for a member (TEC-1845).

Imported at the bottom of service/api/__init__.py. The public status
routes (/tools/status, /events/status, /matchmaker/status) cannot tell who
is asking, and app_entries can be set to the owner alone, so the web asks
here whether this member may see the new in-app entries. The answer is
{enabled} and nothing else: the allow list never leaves the API.
"""
from __future__ import annotations

import duotypes as t
from service.api.decorators import aget

_NO_STORE = {'Cache-Control': 'no-store'}


@aget('/app-entries/status')
def get_app_entries_status(s: t.SessionInfo):
    from service.app_entries import enabled_for
    return dict(enabled=enabled_for(s.person_id, s.email)), 200, _NO_STORE
