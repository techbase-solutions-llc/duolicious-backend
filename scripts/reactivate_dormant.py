"""Bring back the members the dormancy cron hid (TEC-1607).

    PYTHONPATH=/app python3 scripts/reactivate_dormant.py [--dry-run]

Owner decision 1 Oct 2026: an inactive profile stays visible on the map and
in the feed. The cron that set `activated = FALSE` after 30 days offline is
now in dry run (docker-compose.production.yml), and this puts back the
members it already hid. It never touches an account that asked to be
deleted: that one is leaving, not resting.

Idempotent: a reactivated member no longer matches, so a second run is a
no-op. Club counts are not re-incremented because the cron's decrement only
ever ran for members in a club, and none of the 24 is in one (read from
production on 1 Oct 2026). If that changes, re-count before running.
"""
from __future__ import annotations

import argparse

from database import api_tx

_Q = """
    UPDATE person SET activated = TRUE
     WHERE NOT activated AND deletion_requested_at IS NULL
    RETURNING id AS person_id, email
"""
_Q_DRY = """
    SELECT id AS person_id, email FROM person
     WHERE NOT activated AND deletion_requested_at IS NULL
"""


def reactivate_dormant(tx, dry_run: bool = False) -> list[dict]:
    return [dict(r) for r in tx.execute(_Q_DRY if dry_run else _Q).fetchall()]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    with api_tx() as tx:
        rows = reactivate_dormant(tx, a.dry_run)
    print(f"{'would reactivate' if a.dry_run else 'reactivated'} {len(rows)}")
    for r in rows:
        print(' ', r['person_id'])
