"""Test accounts are kept apart from members (TEC-2135).

The owner, 6 Nov 2026, on a tester's account getting likes from real
members: test accounts are hidden from the actual app users, and only test
accounts interact with each other.

A tester is a person whose `roles` holds 'tester' (granted in the admin
user drawer, PATCH /admin/users/<uuid>/roles). Two rules follow:

- Member-facing surfaces: a tester and a non-tester never see or reach each
  other. The SQL function `is_tester_split_pair(a, b)` (migration 0095)
  says so for a pair, and `is_blocked_pair` and `is_deck_suppressed` both
  include it, so every surface that hides a reported or unmatched pair
  hides a split pair too. Staff who are not testers are never split.
- Campaign email, digests and member counts leave testers out. They all
  bind `%(ex)s` from service.growth.queries._excluded(), which adds
  `tester_emails()` to its list.
"""
from __future__ import annotations

import threading
import time

TESTER_ROLE = 'tester'


def tester_sql(alias: str) -> str:
    """SQL boolean: the person row aliased `alias` is a tester."""
    return f"('{TESTER_ROLE}' = ANY(COALESCE({alias}.roles, ARRAY[]::text[])))"


def split_pair_sql(a: str, b: str) -> str:
    """SQL boolean: the two person id expressions are a tester and a
    non-tester (and the non-tester is not staff)."""
    return f"is_tester_split_pair({a}, {b})"


# Every caller of _excluded() calls it inside its own api_tx, and api_tx is
# one shared connection behind a lock that is not re-entrant, so the lookup
# runs on a short-lived connection of its own. Cached per process for a
# minute: _excluded() is called once per query, sometimes per member in a
# cron loop. The roles route forgets the cache in its own process.
_TTL_SECONDS = 60.0
_cache: tuple[float, list[str]] | None = None
_lock = threading.Lock()

_Q_TESTER_EMAILS = f"""
    SELECT DISTINCT lower(email) AS email
      FROM person
     WHERE '{TESTER_ROLE}' = ANY(COALESCE(roles, ARRAY[]::text[]))
       AND email IS NOT NULL
"""


def _read_tester_emails() -> list[str]:
    import psycopg

    import database
    with psycopg.connect(database._api_conninfo, autocommit=True) as conn:
        return [r[0] for r in conn.execute(_Q_TESTER_EMAILS).fetchall()]


def tester_emails() -> list[str]:
    """The lower-cased email of every tester."""
    global _cache
    with _lock:
        now = time.monotonic()
        if _cache is not None and now - _cache[0] < _TTL_SECONDS:
            return list(_cache[1])
        emails = _read_tester_emails()
        _cache = (now, emails)
        return list(emails)


def forget_tester_emails() -> None:
    """Drop the cached list, so the next _excluded() reads it again."""
    global _cache
    with _lock:
        _cache = None
