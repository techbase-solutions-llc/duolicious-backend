"""E1 to the members with push off (TEC-2113; plan
docs/plans/2026-11-05-spotlight-opt-in-prompts.md).

    python -m emails.send_spotlight_announcement_push_off [--send] [--campaign-id ID]

The Spotlight announcement, E1's own builder (a fresh single-use confirm
link per member, none on a dry run), sent from the Growth tab as its own row.
Members with push on are asked by the `spotlight_push` push
(service/spotlight/prompts.py) instead.

Who: activated members, not staff (admin or mod) or a test address, who
have not opted in to Spotlight, have no push subscription, have not left
campaign email, whose address is not suppressed, and who have not had this
email before. Once per member ever.

Self-capped (SELF_CAPPED_CAMPAIGNS): queued exempt, so the weekly E2 does
not hold it back, and it does not hold the next E2 back. Its settings link
is counted under its own name, so the row shows its own clicks.
"""
from __future__ import annotations

import argparse
import uuid

from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.send_spotlight_announcement import build as _build_e1
from emails.spotlight_announcement import FROM_ADDR
from service.campaigns import suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.runner import audit_send, run_campaign
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.man_woman import staff_sql
from service.unsubscribe import make_url as _unsub_url

CAMPAIGN = 'e1_push_off'
UNSUB_SCOPE = 'campaigns'
# Exempt from the cross-campaign cap, and once per member ever (the query).
EXEMPT = True
CAP_DAYS = 0

_WHERE = f"""
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND NOT {staff_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT p.spotlight_opt_in
       AND NOT EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id)
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{CAMPAIGN}')
       AND NOT EXISTS (SELECT 1 FROM email_outbox o
                        WHERE o.person_id = p.id AND o.campaign = '{CAMPAIGN}'
                          AND o.state NOT IN ('failed', 'skipped'))
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""
_Q_RECIPIENTS = f"SELECT p.id AS person_id, p.email, p.name FROM person p {_WHERE} ORDER BY p.id"
_Q_COUNT = f"SELECT count(*) AS n FROM person p {_WHERE}"


def _params() -> dict:
    return dict(ex=_excluded(), sup=suppressed_sql_pattern())


def recipients() -> list[dict]:
    """Opens its own transaction: never call it while holding one."""
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(_Q_RECIPIENTS, _params()).fetchall()]


def recipient_count() -> int:
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_COUNT, _params()).fetchone()['n'])


def build_for(row: dict) -> tuple[str, str]:
    return _build_e1(row, link_kind=CAMPAIGN)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    ap.add_argument('--campaign-id', default=None)
    a = ap.parse_args()
    cid = a.campaign_id or f"{CAMPAIGN}-{uuid.uuid4().hex[:8]}"
    res = run_campaign(api_tx, CAMPAIGN, cid, recipients(), build_for, send=a.send, from_addr=FROM_ADDR,
                       unsub_scope=UNSUB_SCOPE, cap_days=CAP_DAYS, exempt=EXEMPT,
                       list_unsubscribe=lambda e: f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)}>")
    if a.send:
        with api_tx() as tx:
            audit_send(tx, 'cli', CAMPAIGN, res)
    print(res)


if __name__ == '__main__':
    main()
