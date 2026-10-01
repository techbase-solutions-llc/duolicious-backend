"""One push to the members who drifted away and allowed push (TEC-1607).

    PYTHONPATH=/app python3 scripts/push_reactivation.py [--dry-run] [--offline-days 30]

There is no broadcast in the product and this does not add one: it is a
one-off over the same per-member sender every match and message uses. It
picks members offline for `offline_days` who hold a push subscription, have
at least one newcomer matching what they are looking for, have not
unsubscribed from notifications, and are not staff. Counts, never names.
"""
from __future__ import annotations

import argparse

from database import api_tx
from service.campaigns import campaign_unsubscribed
from service.growth.queries import _excluded, count_all_newcomers_since, count_newcomers_since

TITLE = "People are joining Ahavah"
URL = "/discover"
TAG = "reactivation-2026-10"

_Q = """
    SELECT p.id AS person_id, p.last_online_time
      FROM person p
     WHERE p.last_online_time < NOW() - make_interval(days => %(days)s)
       AND p.deletion_requested_at IS NULL
       AND 'admin' <> ALL(COALESCE(p.roles, ARRAY[]::text[]))
       AND lower(p.email) <> ALL(%(ex)s)
       AND EXISTS (SELECT 1 FROM push_subscription s WHERE s.person_id = p.id)
     ORDER BY p.id
"""


def body_for(total_new: int) -> str:
    noun = "new member" if total_new == 1 else "new members"
    return f"{total_new} {noun} since you were last here. Come and see who."


def select_recipients(tx, offline_days: int = 30) -> list[dict]:
    out = []
    for r in tx.execute(_Q, dict(days=offline_days, ex=_excluded())).fetchall():
        if campaign_unsubscribed(tx, r['person_id'], 'notifications'):
            continue
        # Prefer the people they are looking for; fall back to everyone who
        # joined (owner decision 1 Oct 2026: nobody is skipped). The body
        # says "new members" either way, so it never claims a match.
        n = count_newcomers_since(tx, r['person_id'], r['last_online_time']) \
            or count_all_newcomers_since(tx, r['person_id'], r['last_online_time'])
        if n:
            out.append(dict(person_id=r['person_id'], total_new=int(n)))
    return out


def send_all(rows: list[dict], send) -> None:
    """`send` is `service.notifications._send_to_user_blocking`, which opens
    its own transactions, so this runs outside any."""
    for r in rows:
        send(r['person_id'], dict(title=TITLE, body=body_for(r['total_new']), url=URL, tag=TAG))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--offline-days', type=int, default=30)
    a = ap.parse_args()
    with api_tx('read committed') as tx:
        rows = select_recipients(tx, a.offline_days)
    print(f"{len(rows)} recipients: " + ', '.join(f"{r['person_id']} ({r['total_new']})" for r in rows))
    if not a.dry_run:
        from service.notifications import _send_to_user_blocking
        send_all(rows, _send_to_user_blocking)
        print('sent')
