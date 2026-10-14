"""python -m emails.send_spotlight_announcement [--send] [--campaign-id ID] [--preview you@x]"""
from __future__ import annotations

import argparse, uuid
from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.spotlight_announcement import spotlight_announcement_html, SUBJECT, FROM_ADDR
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.runner import audit_send, run_campaign
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.spotlight import spotlight_confirm_url
from service.unsubscribe import make_url as _unsub_url

UNSUB_SCOPE = 'campaigns'

# The same suppression + scope-unsubscribe filters run_campaign() applies
# per-row (see service/campaigns/runner.py) are baked into these queries too,
# so recipient_count() and recipients() (what a run
# actually sends) can never drift from what a real send would do.
_Q_RECIPIENTS = f"""
    SELECT p.id AS person_id, p.email, p.name FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
     ORDER BY p.id
"""

def build_for(row: dict) -> tuple[str, str]:
    return build(row)


def build(row: dict, *, new_copy: bool | None = None) -> tuple[str, str]:
    """`new_copy` None follows AHAVAH_SPOTLIGHT_COPY_ENABLED; the resend
    (emails/send_spotlight_resend.py) passes True."""
    # Mints a real single-use nonce (service.spotlight.nonce.issue_nonce)
    # against the recipient's current consent epoch. Not on a dry run: the
    # runner marks the row, and the token then carries a placeholder nonce
    # that is never stored (health review, 13 Oct 2026; until then a dry
    # run wrote one spotlight_token_nonce row per recipient).
    #
    # Both links go through /s/ campaign links of kind 'e1', with the reader
    # as the link's subject (finding 90): a view of the confirm page used to
    # leave no trace, so nobody could tell whether the copy or the reach was
    # the problem. The click is counted on the way through; the consent
    # record is still written only by the confirm POST.
    dry = row.get('dry_run', False)
    with api_tx() as tx:
        confirm_url = spotlight_confirm_url(tx, row['email'], dry_run=dry)
        if confirm_url is not None:
            subject_id = row['person_id'] or None
            confirm_url = make_campaign_link(tx, 'e1', confirm_url, subject_id, dry_run=dry)
            settings_url = make_campaign_link(tx, 'e1', f"{WEB_BASE_URL}/settings/privacy",
                                              subject_id, dry_run=dry)
    if confirm_url is None:
        # No activated person matches this email (deactivated, deleted, or
        # a bad row) -- there is nothing to mint a token against. Raising
        # here (rather than building a link-less email) makes run_campaign
        # count this recipient as a failure instead of silently sending, or
        # dry-running, a card with href="None".
        raise ValueError('no_person')
    return SUBJECT, spotlight_announcement_html(
        confirm_url,
        settings_url,
        _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
        new_copy=new_copy)

_Q_RECIPIENT_COUNT = f"""
    SELECT count(*) AS n FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""

def recipients() -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(_Q_RECIPIENTS, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall()]

def recipient_count() -> int:
    """How many rows recipients() would return, without materialising them.
    The Growth index stopped calling this on 13 Oct 2026; kept for the CLI and
    the tests that prove the cohort and its count agree. Opens its own transaction, so
    never call it while holding one (the api connection lock is not
    reentrant)."""
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_RECIPIENT_COUNT, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchone()['n'])

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    ap.add_argument('--campaign-id', default=None)
    ap.add_argument('--preview', default=None)
    a = ap.parse_args()
    if a.preview:
        subject, html = build_for(dict(person_id=0, email=a.preview, name='Preview'))
        from smtp import make_aws_smtp
        make_aws_smtp().send(subject=subject, body=html, to_addr=a.preview, from_addr=FROM_ADDR)
        print(f"preview sent to {a.preview}"); return
    cid = a.campaign_id or f"e1-{uuid.uuid4().hex[:8]}"
    res = run_campaign(api_tx, 'e1', cid, recipients(), build_for, send=a.send, from_addr=FROM_ADDR,
                       unsub_scope=UNSUB_SCOPE,
                       list_unsubscribe=lambda e: f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)}>")
    # A real send leaves an audit row, as the Send button's does.
    if a.send:
        with api_tx() as tx:
            audit_send(tx, 'cli', 'e1', res)
    print(res)

if __name__ == '__main__':
    main()
