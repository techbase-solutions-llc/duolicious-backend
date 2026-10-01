"""python -m emails.send_notifications_nudge [--send] [--campaign-id ID]

E6 (TEC-1607): active members with no push subscription are asked to turn
notifications on. Active means online in the last 30 days; the members
offline longer than that are E3's, and get the same ask inside it.
"""
from __future__ import annotations

import argparse, uuid

from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.notifications_nudge import notifications_nudge_html, SUBJECT, FROM_ADDR
from service.campaigns import (make_campaign_link, suppressed_predicate_sql,
                               unsubscribed_predicate_sql)
from service.campaigns.runner import run_campaign
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as _unsub_url

UNSUB_SCOPE = 'notifications'
ACTIVE_DAYS = 30

_WHERE = f"""
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND p.last_online_time >= NOW() - make_interval(days => %(days)s)
       AND 'admin' <> ALL(COALESCE(p.roles, ARRAY[]::text[]))
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT EXISTS (SELECT 1 FROM push_subscription s WHERE s.person_id = p.id)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""
_Q_RECIPIENTS = f"SELECT p.id AS person_id, p.email, p.name FROM person p {_WHERE} ORDER BY p.id"
_Q_RECIPIENT_COUNT = f"SELECT count(*) AS n FROM person p {_WHERE}"


def _params() -> dict:
    return dict(days=ACTIVE_DAYS, ex=_excluded(), sup=suppressed_sql_pattern())


def recipients() -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(_Q_RECIPIENTS, _params()).fetchall()]


def recipient_count() -> int:
    """Opens its own transaction: never call it while holding one."""
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_RECIPIENT_COUNT, _params()).fetchone()['n'])


def build_for(row: dict) -> tuple[str, str]:
    with api_tx() as tx:
        settings_url = make_campaign_link(
            tx, 'e6', f"{WEB_BASE_URL}/settings/notifications", row['person_id'] or None)
    first = (row.get('name') or 'there').split(' ')[0]
    return SUBJECT, notifications_nudge_html(
        first, settings_url, _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL))


def preview_row(to: str) -> dict:
    return dict(person_id=0, email=to, name='Preview')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    ap.add_argument('--campaign-id', default=None)
    a = ap.parse_args()
    cid = a.campaign_id or f"e6-{uuid.uuid4().hex[:8]}"
    print(run_campaign(api_tx, 'e6', cid, recipients(), build_for, send=a.send, from_addr=FROM_ADDR,
                       unsub_scope=UNSUB_SCOPE,
                       list_unsubscribe=lambda e: f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)}>"))


if __name__ == '__main__':
    main()
