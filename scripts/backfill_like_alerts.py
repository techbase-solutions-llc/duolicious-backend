"""Turn like push on for people who already hold a push subscription.

    PYTHONPATH=/app python3 scripts/backfill_like_alerts.py [--dry-run]

Health review, 13 Oct 2026 (findings 32, 58): the push banner, E3 and E6
promise like alerts, but subscribing never turned `push_likes` on, so on
13 Oct 13 people held a subscription (11 members, 2 staff) and none had
like push. From this deploy a subscribe turns it on
(service.notifications.post_subscribe); this does the same for the people
who subscribed before, by the same statement
(`Q_LIKE_PUSH_ON_UNLESS_CHOSEN`).

Left alone: anyone who has chosen about likes (`push_likes_chosen_at` is
set, migration 0057) and anyone already on. Staff accounts are included,
as the subscribe route includes them; the counts say how many.

Idempotent: a second run finds nobody. Prints counts only.
"""
from __future__ import annotations

import argparse

from database import api_tx
from service.admin.queries.members import member_sql
from service.notifications import Q_LIKE_PUSH_ON_UNLESS_CHOSEN

# Who the statement would turn on: holds a subscription, has no preference
# row, or has one that is off and was never chosen.
_Q_CANDIDATES = f"""
    SELECT p.id, {member_sql('p')} AS is_member
      FROM person p
      LEFT JOIN notification_preference np ON np.person_id = p.id
     WHERE EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id)
       AND (np.person_id IS NULL
            OR (NOT np.push_likes AND np.push_likes_chosen_at IS NULL))
"""


def backfill(tx, dry_run: bool = False) -> dict:
    """On a dry run, `would_turn_on` and its split; on a real run,
    `turned_on` is the people the statement actually changed."""
    rows = tx.execute(_Q_CANDIDATES).fetchall()
    members = sum(1 for r in rows if r['is_member'])
    out = dict(members=members, staff=len(rows) - members)
    if dry_run:
        return dict(out, would_turn_on=len(rows))
    done = tx.execute(Q_LIKE_PUSH_ON_UNLESS_CHOSEN,
                      dict(ids=[r['id'] for r in rows])).fetchall()
    return dict(out, turned_on=len(done))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    with api_tx() as tx:
        out = backfill(tx, dry_run=a.dry_run)
    if a.dry_run:
        print(f"would turn like push on for {out['would_turn_on']} subscriber(s) "
              f"({out['members']} members, {out['staff']} staff)")
        print('dry run, nothing written')
    else:
        print(f"turned like push on for {out['turned_on']} subscriber(s) "
              f"({out['members']} members, {out['staff']} staff found)")


if __name__ == '__main__':
    main()
