"""One push to the members who drifted away and allowed push (TEC-1607).

    PYTHONPATH=/app python3 scripts/push_reactivation.py [--dry-run] [--offline-days 30]

There is no broadcast in the product and this does not add one: it is a
one-off over the same per-member sender every match and message uses. It
picks members offline for `offline_days` who hold a push subscription, have
at least one newcomer matching what they are looking for, have not
unsubscribed from notifications, and are not staff. Counts, never names.

Each push writes a push_send_log row first (send safeguards, 2 Nov 2026), so
anyone already pushed is neither picked nor pushed again by a second run.
"""
from __future__ import annotations

import argparse

from database import api_tx
from service.campaigns import campaign_unsubscribed
from service.growth.queries import _excluded, count_all_newcomers_since, count_newcomers_since

TITLE = "People are joining Ahavah"
URL = "/discover"
TAG = "reactivation-2026-10"
# The push_send_log key: one push per member for this one-off.
CAMPAIGN = "reactivation"
CAMPAIGN_ID = TAG

_Q = """
    SELECT p.id AS person_id, p.last_online_time
      FROM person p
     WHERE p.last_online_time < NOW() - make_interval(days => %(days)s)
       AND p.deletion_requested_at IS NULL
       AND 'admin' <> ALL(COALESCE(p.roles, ARRAY[]::text[]))
       AND lower(p.email) <> ALL(%(ex)s)
       AND EXISTS (SELECT 1 FROM push_subscription s WHERE s.person_id = p.id)
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = %(c)s AND l.campaign_id = %(cid)s)
     ORDER BY p.id
"""


def body_for(total_new: int) -> str:
    noun = "new member" if total_new == 1 else "new members"
    return f"{total_new} {noun} since you were last here. Come and see who."


def select_recipients(tx, offline_days: int = 30) -> list[dict]:
    out = []
    for r in tx.execute(_Q, dict(days=offline_days, ex=_excluded(), c=CAMPAIGN, cid=CAMPAIGN_ID)).fetchall():
        # A member who left campaigns (or every email, the old way) is not
        # sent a campaign push either.
        if campaign_unsubscribed(tx, r['person_id'], 'campaigns'):
            continue
        # Prefer the people they are looking for; fall back to everyone who
        # joined (owner decision 1 Oct 2026: nobody is skipped). The body
        # says "new members" either way, so it never claims a match.
        n = count_newcomers_since(tx, r['person_id'], r['last_online_time']) \
            or count_all_newcomers_since(tx, r['person_id'], r['last_online_time'])
        if n:
            out.append(dict(person_id=r['person_id'], total_new=int(n)))
    return out


def claim(person_id: int) -> bool:
    """Write this member's push_send_log row in its own transaction. False
    when the row was already there: that member has had this push."""
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO push_send_log (person_id, campaign, campaign_id)
               VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
            dict(p=person_id, c=CAMPAIGN, cid=CAMPAIGN_ID)).fetchone() is not None


def send_all(rows: list[dict], send, claim=None) -> None:
    """`send` is `service.notifications._send_to_user_blocking`, which opens
    its own transactions, so this runs outside any. `claim` (the real run
    passes `claim` above) records each member before the push and skips
    anyone it has recorded already; a crash between the two loses that one
    push, which is the right way for a one-off to fail."""
    for r in rows:
        if claim is not None and not claim(r['person_id']):
            continue
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
        send_all(rows, _send_to_user_blocking, claim=claim)
        print('sent')
