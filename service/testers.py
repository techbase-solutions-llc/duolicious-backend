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
  hides a split pair too. Staff are no exception in the member app; the
  admin panel still shows everyone.
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
    non-tester."""
    return f"is_tester_split_pair({a}, {b})"


def tester_organiser_sql(organiser_id: str) -> str:
    """SQL boolean: the gathering organiser whose id is the expression
    `organiser_id` is a tester's (TEC-2085, decision 3 as revised on 13 Nov
    2026). An organiser is a tester's when the member who made it in the
    app (member_person_id) or the account under its address is a tester,
    the two ways a member's session opens an organiser
    (service.events.organisers.member_organisers).

    A tester's gathering shows only to testers: never to members or
    signed-out visitors, in no list, page, sitemap, email or post."""
    return f"""EXISTS (
        SELECT 1 FROM organiser t_o
          JOIN person t_p ON t_p.id = t_o.member_person_id
                          OR t_p.normalized_email = t_o.normalized_email
         WHERE t_o.id = {organiser_id} AND {tester_sql('t_p')})"""


def is_tester(tx, person_id) -> bool:
    """Whether the person is a tester. No person (a signed-out visitor, a
    session not yet onboarded) is not."""
    if person_id is None:
        return False
    row = tx.execute(f"SELECT {tester_sql('p')} AS t FROM person p WHERE p.id = %(i)s",
                     dict(i=person_id)).fetchone()
    return bool(row and row['t'])


def is_tester_organiser(tx, organiser_id: int) -> bool:
    """tester_organiser_sql for one organiser."""
    row = tx.execute(f"SELECT {tester_organiser_sql('%(o)s::int')} AS t",
                     dict(o=organiser_id)).fetchone()
    return bool(row and row['t'])


# Every caller of _excluded() calls it inside its own api_tx, and api_tx is
# one shared connection behind a lock that is not re-entrant (database/), and
# the repo has no other synchronous pool, so the lookup runs on a short-lived
# connection of its own. Cached per process for a minute: _excluded() is
# called once per query, sometimes per member in a cron loop. The roles route
# forgets the cache in its own process.
#
# It never fails its caller: a campaign or a count must not stop because the
# lookup could not connect. On an error it returns the last list it read ([]
# before the first), logs the error class once, and tries again after
# _RETRY_SECONDS. The lock is never held while connecting.
_TTL_SECONDS = 60.0
_RETRY_SECONDS = 10.0
_CONNECT_TIMEOUT_SECONDS = 3
_cache: tuple[float, list[str]] | None = None
_retry_after = 0.0
_failure_logged = False
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
    with psycopg.connect(database._api_conninfo, autocommit=True,
                         connect_timeout=_CONNECT_TIMEOUT_SECONDS) as conn:
        return [r[0] for r in conn.execute(_Q_TESTER_EMAILS).fetchall()]


def tester_emails() -> list[str]:
    """The lower-cased email of every tester (see above for the cache and
    what happens when the lookup fails)."""
    global _cache, _retry_after, _failure_logged
    now = time.monotonic()
    with _lock:
        cached, retry_after = _cache, _retry_after
    if cached is not None and now - cached[0] < _TTL_SECONDS:
        return list(cached[1])
    if now < retry_after:
        return list(cached[1]) if cached is not None else []
    try:
        emails = _read_tester_emails()
    except Exception as e:  # never fail the caller
        with _lock:
            _retry_after = time.monotonic() + _RETRY_SECONDS
            if not _failure_logged:
                print(f'testers: the tester email lookup failed ({type(e).__name__}); '
                      'using the last list read')
                _failure_logged = True
            return list(_cache[1]) if _cache is not None else []
    with _lock:
        _cache = (time.monotonic(), emails)
        _retry_after = 0.0
        _failure_logged = False
    return list(emails)


def forget_tester_emails() -> None:
    """Drop the cached list, so the next _excluded() reads it again."""
    global _cache, _retry_after
    with _lock:
        _cache = None
        _retry_after = 0.0
