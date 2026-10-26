"""A member's Discover filters, kept with the account (TEC-1845).

The web app's Filters sheet (ahavah-web src/components/app/filters-sheet.tsx)
used to keep its choices only in the browser, and sign-out removes them
there so the next person on a shared device does not get them. A member who
signed in again or opened Ahavah on another device found them gone (owner,
25 Oct). GET /discover-filters gives the saved set back and PUT saves it;
the browser's copy is a cache.

The keys are the web's own (DiscoverFiltersState). /search still takes the
filters as query parameters; nothing here changes who the deck shows.
`normalise` keeps only the keys below, in the shapes below: an age bound is
a whole year from 18 to 80, a list holds short slug or code values, a flag
is stored only when it is on. A key this version does not know is dropped,
so a newer web app can still save the rest.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from database import api_tx
from service.search import AGE_CEILING, AGE_FLOOR

AGE_KEYS = ('ageMin', 'ageMax')
LIST_KEYS = (
    'assemblies', 'torahLevels', 'polygynyStances', 'intents', 'calendars',
    'healthTags', 'educations', 'maritalStatuses', 'hasChildrenBuckets',
    'country', 'languages',
)
FLAG_KEYS = ('verifiedOnly', 'mapLens')

# Every country fits (the map can select all of them); 300 bounds the rest.
MAX_LIST = 300
_VALUE = re.compile(r'^[A-Za-z0-9-]{1,64}$')


class BadFilters(Exception):
    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def normalise(raw: Any) -> dict:
    """The filters as stored, or BadFilters naming the first wrong field."""
    if not isinstance(raw, dict):
        raise BadFilters('filters')
    out: dict = {}
    for key in AGE_KEYS:
        v = raw.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or not AGE_FLOOR <= v <= AGE_CEILING:
            raise BadFilters(key)
        out[key] = v
    if 'ageMin' in out and 'ageMax' in out and out['ageMin'] > out['ageMax']:
        raise BadFilters('ageMin')
    for key in LIST_KEYS:
        v = raw.get(key)
        if v is None:
            continue
        if (not isinstance(v, list) or len(v) > MAX_LIST
                or not all(isinstance(x, str) and _VALUE.match(x) for x in v)):
            raise BadFilters(key)
        values = list(dict.fromkeys(v))
        if values:
            out[key] = values
    for key in FLAG_KEYS:
        v = raw.get(key)
        if v is None:
            continue
        if not isinstance(v, bool):
            raise BadFilters(key)
        if v:
            out[key] = True
    return out


Q_LOAD = 'SELECT filters FROM discover_filters WHERE person_id = %(p)s'

Q_SAVE = """
    INSERT INTO discover_filters (person_id, filters, updated_at)
    VALUES (%(p)s, %(f)s::jsonb, NOW())
    ON CONFLICT (person_id) DO UPDATE
       SET filters = EXCLUDED.filters, updated_at = NOW()
"""


def load(person_id: int) -> Optional[dict]:
    """The member's saved filters, or None when they never saved any."""
    with api_tx('READ COMMITTED') as tx:
        row = tx.execute(Q_LOAD, dict(p=person_id)).fetchone()
    return row['filters'] if row else None


def save(person_id: int, raw: Any) -> dict:
    """Store the filters (normalised) and return what was stored."""
    filters = normalise(raw)
    with api_tx() as tx:
        tx.execute(Q_SAVE, dict(p=person_id, f=json.dumps(filters)))
    return filters
