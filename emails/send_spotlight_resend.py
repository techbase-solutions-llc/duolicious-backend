"""E1 once more, to the members who never received it (health review,
13 Oct 2026, finding 80).

E1 reached 24 people on 20 Sep; 34 members have joined or been missed
since. Each email mints a fresh single-use token (the 20 Sep tokens stop
working about 20 Oct), carries the copy that matches the web lane's
Spotlight strings ("your main profile photo"), and counts its settings link
through /s/ like E1 (finding 90); the confirm link, which carries the token,
goes direct. Campaign `e1`, so the Growth tab counts it with E1; unsubscribe
scope `campaigns`.

Who: activated members, staff test accounts left out, who have no `e1` row
in the send log, have not already opted in, and have not left campaigns.

Held. A real send is refused unless AHAVAH_E1_RESEND_ENABLED is on.

    python -m emails.send_spotlight_resend                 # dry run, writes nothing
    python -m emails.send_spotlight_resend --send          # queue (switch must be on)

`--cap-days` is the cross-campaign cap the runner and the drain apply
(default 6). E2 goes to every member each Monday, so a run on a Monday
after the weekly email with `--cap-days 0` reaches everyone and leaves the
next Monday's E2 outside its own 6 day cap.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Optional

from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.send_spotlight_announcement import build as _build_e1
from emails.spotlight_announcement import FROM_ADDR, SUBJECT, spotlight_announcement_html
from service.campaigns import suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.runner import audit_send, run_campaign
from service.campaigns.switches import enabled
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as _unsub_url

CAMPAIGN = 'e1'
UNSUB_SCOPE = 'campaigns'
SWITCH = 'e1_resend'

_WHERE = f"""
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT p.spotlight_opt_in
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = 'e1')
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""
_Q_RECIPIENTS = f"SELECT p.id AS person_id, p.email, p.name FROM person p {_WHERE} ORDER BY p.id"
_Q_COUNT = f"SELECT count(*) AS n FROM person p {_WHERE}"


def recipients() -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            _Q_RECIPIENTS, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall()]


def recipient_count() -> int:
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_COUNT, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchone()['n'])


def build_for(row: dict) -> tuple[str, str]:
    """E1's own builder with the new copy: a fresh token per member (none
    on a dry run) and a counted settings link."""
    return _build_e1(row, new_copy=True)


def run(*, send: bool, campaign_id: Optional[str] = None, cap_days: int = 6,
        only_ids: Optional[list[int]] = None) -> dict:
    """Queue (or, with send False, build and count) the resend. A real send
    is refused while the switch is off."""
    if send and not enabled(SWITCH):
        return dict(error='switch_off', queued=0)
    cid = campaign_id or f"e1-resend-{datetime.now(timezone.utc):%Y%m%d}"
    rows = recipients()
    if only_ids is not None:
        rows = [r for r in rows if r['person_id'] in set(only_ids)]
    res = run_campaign(
        api_tx, CAMPAIGN, cid, rows, build_for, send=send, from_addr=FROM_ADDR,
        unsub_scope=UNSUB_SCOPE, cap_days=cap_days,
        list_unsubscribe=lambda e: (f"<mailto:support@ahavah.app?subject=Unsubscribe>, "
                                    f"<{_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)}>"))
    if send:
        with api_tx() as tx:
            audit_send(tx, 'cli', CAMPAIGN, res)
    return res


def preview(to: str) -> tuple[str, str]:
    """The proof: the resend's copy with plain links. Mints no token and
    stores nothing, so its button shows the confirm page's not-valid state."""
    return SUBJECT, spotlight_announcement_html(
        f"{WEB_BASE_URL}/spotlight/confirm/proof", f"{WEB_BASE_URL}/settings/privacy",
        _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL), new_copy=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    ap.add_argument('--campaign-id', default=None)
    ap.add_argument('--cap-days', type=int, default=6)
    a = ap.parse_args()
    print(run(send=a.send, campaign_id=a.campaign_id, cap_days=a.cap_days))


if __name__ == '__main__':
    main()
