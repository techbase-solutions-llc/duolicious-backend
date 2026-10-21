"""SQL fragments the deck and the matchmaker's alerts share (TEC-1845).

The matchmaker tells a member how many new members fit what they are
looking for. If its idea of "fits" drifted from the deck's, an alert could
count someone the deck would never show, so both read the same text:
Q_UNCACHED_SEARCH_2 interpolates these (word for word what it said on
20 Oct, tests/test_search_predicates.py) and service/matchmaker/criteria
builds its count from them.

Each function takes the SQL alias of the prospect's `person` row and
returns a boolean expression in parentheses, with the bind names the deck
already uses. Every one fails open on an unset prospect field, as the deck
does: unknown is not a mismatch.
"""
from __future__ import annotations

from typing import Optional

from service.admin.queries.members import member_sql


def gender_sql(p: str) -> str:
    """%(gender_preference)s: the searcher's genders; empty = any."""
    return f"""(
          cardinality(%(gender_preference)s::SMALLINT[]) = 0
          OR {p}.gender_id = ANY(%(gender_preference)s::SMALLINT[])
      )"""


def torah_level_sql(p: str) -> str:
    """%(torah_levels)s: profile torahLevel values; empty = any."""
    return f"""(
          cardinality(%(torah_levels)s::TEXT[]) = 0
          OR {p}.ahavah_extra->>'torahLevel' = ANY(%(torah_levels)s::TEXT[])
          OR {p}.ahavah_extra->>'torahLevel' IS NULL
      )"""


def calendar_sql(p: str) -> str:
    """%(calendars)s: profile calendar values; empty = any."""
    return f"""(
          cardinality(%(calendars)s::TEXT[]) = 0
          OR {p}.ahavah_extra->>'calendar' = ANY(%(calendars)s::TEXT[])
          OR {p}.ahavah_extra->>'calendar' IS NULL
      )"""


def age_bounds_sql(p: str) -> str:
    """%(age_min)s, %(age_max)s: inclusive whole years; NULL = open."""
    return f"""(
          %(age_min)s::INT IS NULL
          OR EXTRACT(YEAR FROM AGE({p}.date_of_birth))::INT >= %(age_min)s::INT
      )
      AND (
          %(age_max)s::INT IS NULL
          OR EXTRACT(YEAR FROM AGE({p}.date_of_birth))::INT <= %(age_max)s::INT
      )"""


# The alert's own criteria, not in the deck's Filters yet (brief decision
# 1, option A: they live in the alert sheet only).

def countries_sql(p: str) -> str:
    """%(countries)s: alpha-2 codes; empty = any; no country = unknown."""
    return f"""(
          cardinality(%(countries)s::TEXT[]) = 0
          OR upper({p}.country) = ANY(%(countries)s::TEXT[])
          OR {p}.country IS NULL
          OR {p}.country = ''
      )"""


def relocation_sql(p: str) -> str:
    """%(relocations)s: profile relocation values; empty = any."""
    return f"""(
          cardinality(%(relocations)s::TEXT[]) = 0
          OR {p}.ahavah_extra->>'relocation' = ANY(%(relocations)s::TEXT[])
          OR {p}.ahavah_extra->>'relocation' IS NULL
      )"""


def shabbat_sql(p: str) -> str:
    """%(shabbats)s: profile shabbat values; empty = any."""
    return f"""(
          cardinality(%(shabbats)s::TEXT[]) = 0
          OR {p}.ahavah_extra->>'shabbat' = ANY(%(shabbats)s::TEXT[])
          OR {p}.ahavah_extra->>'shabbat' IS NULL
      )"""


def wants_children_sql(p: str) -> str:
    """%(wants_children)s: 'yes', 'no' or NULL (any)."""
    return f"""(
          %(wants_children)s::TEXT IS NULL
          OR {p}.ahavah_extra->>'wantsChildren' = %(wants_children)s::TEXT
          OR {p}.ahavah_extra->>'wantsChildren' IS NULL
      )"""


def deck_base_sql(p: str, owner: Optional[str]) -> str:
    """Whom the deck could show at all: activated, a member (not staff),
    not hidden from strangers, not held for verification, with an approved
    photo. With `owner` (an SQL expression for the viewer's person id), not
    the viewer, and no block or unmatch between the two either way. A
    visitor (owner None) has no pairs."""
    pairs = ''
    if owner is not None:
        pairs = f"""
      AND {p}.id <> {owner}
      AND NOT is_blocked_pair({owner}, {p}.id)
      AND NOT is_unmatched_pair({owner}, {p}.id)"""
    return f"""(
      {p}.activated
      AND {member_sql(p)}
      AND NOT {p}.hide_me_from_strangers
      AND NOT {p}.verification_required
      AND EXISTS (
          SELECT 1 FROM photo ph_base
          WHERE ph_base.person_id = {p}.id
            AND ph_base.moderation_status = 'approved'
      ){pairs}
  )"""
