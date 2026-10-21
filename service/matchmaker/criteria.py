"""What an alert looks for, the words for it and the fit query (TEC-1845).

A member's criteria (the alert sheet, 1.1): an age band, countries or the
continents a visitor's alert carried in, relocation, Torah observance, the
Sabbath, the calendar and whether they want children. A visitor's (3.1):
a man or a woman, an age band and a continent or anywhere.

Allowed values are the web's lists (ahavah-web src/lib/profile-schema.ts).
A list with every option is no filter and is stored empty. Every criterion
fails open on a member who never answered it, as the deck does.

The fit query is the deck's own clauses (service/search/predicates.py), so
an alert never counts someone the deck would not show.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from service.matchmaker import MatchmakerError
from service.matchmaker.regions import LABELS, REGIONS, codes_in, is_country
from service.search import AGE_CEILING, AGE_FLOOR
from service.search import predicates as pr

MEMBER_KEYS = ('age_min', 'age_max', 'countries', 'regions', 'relocations', 'torah_levels',
               'shabbats', 'calendars', 'wants_children')
VISITOR_KEYS = ('looking_for', 'age_min', 'age_max', 'region')

RELOCATIONS = ('will-relocate', 'wants-partner-willing', 'local-only', 'international-open')
TORAH_LEVELS = ('learning', 'beginner', 'intermediate', 'experienced')
SHABBATS = ('friday-sunset-saturday-sunset', 'luni-solar', 'saturday-only', 'other')
CALENDARS = ('rabbinic', 'aviv-barley', 'enoch', 'luni-solar', 'observational-new-moon', 'other')
WANTS_CHILDREN = ('yes', 'no')
LOOKING_FOR = ('man', 'woman')

_LISTS = {
    'regions': REGIONS,
    'relocations': RELOCATIONS,
    'torah_levels': TORAH_LEVELS,
    'shabbats': SHABBATS,
    'calendars': CALENDARS,
}


def _bad(field: str) -> MatchmakerError:
    return MatchmakerError('bad_criteria', 400, {'field': field})


def _age(raw: dict, key: str) -> int:
    v = raw.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not AGE_FLOOR <= v <= AGE_CEILING:
        raise _bad(key)
    return v


def _ages(raw: dict) -> tuple[int, int]:
    lo, hi = _age(raw, 'age_min'), _age(raw, 'age_max')
    if lo > hi:
        raise _bad('age_min')
    return lo, hi


def _choices(raw: dict, key: str, allowed: tuple[str, ...]) -> list[str]:
    v = raw.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x in allowed for x in v):
        raise _bad(key)
    out = list(dict.fromkeys(v))
    return [] if set(out) == set(allowed) else out


def _countries(raw: dict) -> list[str]:
    v = raw.get('countries')
    if v is None:
        return []
    if not isinstance(v, list) or not all(is_country(x) for x in v):
        raise _bad('countries')
    return list(dict.fromkeys(x.strip().upper() for x in v))


def clean_member_criteria(raw: dict) -> dict:
    """A member's criteria, checked. Raises MatchmakerError('bad_criteria',
    400, {'field': key}) naming the first criterion that is wrong."""
    if not isinstance(raw, dict):
        raise _bad('criteria')
    for key in raw:
        if key not in MEMBER_KEYS:
            raise _bad(key)
    lo, hi = _ages(raw)
    out: dict = dict(age_min=lo, age_max=hi, countries=_countries(raw))
    for key, allowed in _LISTS.items():
        out[key] = _choices(raw, key, allowed)
    # Choosing countries replaces a continent the visitor's alert carried.
    if out['countries']:
        out['regions'] = []
    wc = raw.get('wants_children')
    if wc is not None and wc not in WANTS_CHILDREN:
        raise _bad('wants_children')
    out['wants_children'] = wc
    return {k: out[k] for k in MEMBER_KEYS}


def clean_visitor_criteria(raw: dict) -> dict:
    """A visitor's criteria: a man or a woman, an age band, a continent or
    None (Anywhere)."""
    if not isinstance(raw, dict):
        raise _bad('criteria')
    for key in raw:
        if key not in VISITOR_KEYS:
            raise _bad(key)
    if raw.get('looking_for') not in LOOKING_FOR:
        raise _bad('looking_for')
    lo, hi = _ages(raw)
    region = raw.get('region')
    if region is not None and region not in REGIONS:
        raise _bad('region')
    return dict(looking_for=raw['looking_for'], age_min=lo, age_max=hi, region=region)


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

def _country_name(code: str) -> str:
    import pycountry
    c = pycountry.countries.get(alpha_2=code)
    return getattr(c, 'common_name', None) or (c.name if c else code)


def _place_words(c: dict) -> str:
    countries = c.get('countries') or []
    regions = c.get('regions') or []
    if countries:
        if len(countries) == 1:
            return f'in {_country_name(countries[0])}'  # NEW LINE
        return f'in {len(countries)} countries'  # NEW LINE
    if regions:
        if len(regions) == 1:
            return f'in {LABELS[regions[0]]}'  # NEW LINE
        if len(regions) == 2:
            return f'in {LABELS[regions[0]]} and {LABELS[regions[1]]}'  # NEW LINE
        return f'in {len(regions)} regions'  # NEW LINE
    return 'anywhere'


def summary_line(c: dict) -> str:
    """The part of 1.9's "On. Ages 26 to 34, anywhere." after "On. "."""
    return f"Ages {c['age_min']} to {c['age_max']}, {_place_words(c)}."


def visitor_words(c: dict) -> str:
    """4.4's "a man aged 26 to 34 in North America"; without a continent,
    "a woman aged 30 to 40" (NEW LINE)."""
    words = f"a {c['looking_for']} aged {c['age_min']} to {c['age_max']}"
    if c.get('region'):
        words += f" in {LABELS[c['region']]}"
    return words


# ---------------------------------------------------------------------------
# The fit query
# ---------------------------------------------------------------------------

def fits_sql(owner: Optional[str]) -> str:
    """A boolean expression on the `person` row aliased p: someone who
    joined in the window (since, until] whom the deck would show the owner
    (`owner` an SQL expression for their person id, None for a visitor),
    inside every criterion. Bind with fit_params."""
    return f"""(
      {pr.deck_base_sql('p', owner)}
      AND {pr.gender_sql('p')}
      AND {pr.age_bounds_sql('p')}
      AND {pr.countries_sql('p')}
      AND {pr.relocation_sql('p')}
      AND {pr.torah_level_sql('p')}
      AND {pr.shabbat_sql('p')}
      AND {pr.calendar_sql('p')}
      AND {pr.wants_children_sql('p')}
      AND p.sign_up_time > (%(since)s::TIMESTAMPTZ AT TIME ZONE 'UTC')
      AND p.sign_up_time <= (%(until)s::TIMESTAMPTZ AT TIME ZONE 'UTC')
  )"""


def fit_params(c: dict, *, gender_ids: list[int], since: datetime, until: datetime,
               owner_id: Optional[int]) -> dict:
    """The binds for fits_sql, from a member's or a visitor's criteria.
    Continents become their countries."""
    countries = list(c.get('countries') or [])
    regions = list(c.get('regions') or ([c['region']] if c.get('region') else []))
    if not countries and regions:
        countries = codes_in(regions)
    return dict(
        gender_preference=list(gender_ids),
        age_min=c.get('age_min'),
        age_max=c.get('age_max'),
        countries=countries,
        relocations=list(c.get('relocations') or []),
        torah_levels=list(c.get('torah_levels') or []),
        shabbats=list(c.get('shabbats') or []),
        calendars=list(c.get('calendars') or []),
        wants_children=c.get('wants_children'),
        since=since,
        until=until,
        owner=owner_id,
    )
