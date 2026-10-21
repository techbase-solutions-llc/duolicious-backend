"""Unhandled API errors, counted per route (TEC-1897, health review finding
17: an admin route failed on every load and nothing showed it).

`connect(app)` subscribes to Flask's got_request_exception, which fires for
every unhandled exception before Flask answers 500. The `validate`
decorator answers its own 500s and calls `record` itself. Each error adds 1
to its route's row for the current hour.

The route is the Flask rule ("/admin/users/<uuid>"), never the path, so no
id or address is stored. Recording must never make an error worse: a
failure here is printed and dropped, and the request goes on to its 500 as
before. It opens its own transaction; the handler's has already ended by
the time the exception reaches Flask, so the non-re-entrant api lock is
free.
"""
from __future__ import annotations

from flask import got_request_exception, request

from database import api_tx

_Q_TALLY = """
    INSERT INTO api_error_tally (route, hour, n, last_at)
    VALUES (%(route)s, date_trunc('hour', NOW()), 1, NOW())
    ON CONFLICT (route, hour) DO UPDATE
       SET n = api_error_tally.n + 1, last_at = EXCLUDED.last_at
"""

_Q_TOTALS = """
    SELECT COALESCE(sum(n) FILTER (
               WHERE hour >= date_trunc('hour', NOW() - INTERVAL '24 hours')), 0)::int AS last_24h,
           COALESCE(sum(n), 0)::int AS last_7d
      FROM api_error_tally
     WHERE hour >= date_trunc('hour', NOW() - INTERVAL '7 days')
"""

_Q_ROUTES = """
    SELECT route, sum(n)::int AS errors, max(last_at) AS last_failed_at
      FROM api_error_tally
     WHERE hour >= date_trunc('hour', NOW() - INTERVAL '7 days')
     GROUP BY route
     ORDER BY errors DESC, route
     LIMIT 10
"""


def route_of() -> str:
    rule = getattr(request, 'url_rule', None)
    return (rule.rule if rule is not None else 'unmatched')[:200]


def record(route: str) -> None:
    try:
        with api_tx() as tx:
            tx.execute(_Q_TALLY, dict(route=route))
    except Exception as e:  # never make the original error worse
        print(f'error_tally: not recorded ({type(e).__name__})')


def _on_exception(sender, exception, **extra) -> None:
    record(route_of())


def connect(app) -> None:
    got_request_exception.connect(_on_exception, app, weak=False)


def summary(tx) -> dict:
    totals = tx.execute(_Q_TOTALS).fetchone()
    routes = [dict(route=r['route'], errors=r['errors'],
                   last_failed_at=r['last_failed_at'].isoformat())
              for r in tx.execute(_Q_ROUTES).fetchall()]
    return dict(last_24h=totals['last_24h'], last_7d=totals['last_7d'], routes=routes)
