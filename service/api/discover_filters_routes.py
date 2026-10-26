"""GET and PUT /discover-filters: a member's Discover filters (TEC-1845).

Imported at the bottom of service/api/__init__.py, as the other sibling
route modules are. See service/discover_filters for what is kept and why.
"""
from __future__ import annotations

import duotypes as t
from service import discover_filters
from service.api.decorators import aget, aput, validate

_NO_STORE = {'Cache-Control': 'no-store'}


@aget('/discover-filters')
def get_discover_filters(s: t.SessionInfo):
    return dict(filters=discover_filters.load(s.person_id)), 200, _NO_STORE


@aput('/discover-filters')
@validate(t.PutDiscoverFilters)
def put_discover_filters(req: t.PutDiscoverFilters, s: t.SessionInfo):
    try:
        saved = discover_filters.save(s.person_id, req.filters)
    except discover_filters.BadFilters as e:
        return dict(error='bad_filters', field=e.field), 400, _NO_STORE
    return dict(filters=saved), 200, _NO_STORE
