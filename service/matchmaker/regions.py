"""A country's continent, for alerts (TEC-1845).

continents.json maps every alpha-2 code pycountry knows to one of the Map's
6 continents by UN M49, with the rules of Gatherings' table
(service/events/continents.json, which is keyed by name): the Caribbean,
Central America and Mexico are North America, Russia is Europe, Turkey and
the Caucasus are Asia, Egypt is Africa. Antarctica, which M49 keeps apart,
is put in Oceania so that no code is left without a region.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

REGIONS = ('africa', 'asia', 'europe', 'north-america', 'oceania', 'south-america')

# The Map's labels (ahavah-web), for the words in an alert.
LABELS = {
    'africa': 'Africa',
    'asia': 'Asia',
    'europe': 'Europe',
    'north-america': 'North America',
    'oceania': 'Oceania',
    'south-america': 'South America',
}


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    path = Path(__file__).resolve().parent / 'continents.json'
    return json.loads(path.read_text(encoding='utf-8'))


def region_of(code: Optional[str]) -> Optional[str]:
    """The continent of an alpha-2 code, or None for none or an unknown one."""
    if not code:
        return None
    return _table().get(code.strip().upper())


def codes_in(regions: Iterable[str]) -> list[str]:
    """Every alpha-2 code in these continents, sorted."""
    wanted = set(regions)
    return sorted(c for c, r in _table().items() if r in wanted)


def is_country(code: object) -> bool:
    return isinstance(code, str) and code.strip().upper() in _table()
