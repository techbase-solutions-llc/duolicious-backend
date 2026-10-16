"""One-off: the owner's personal note to the Spotlight candidates (health
review, 13 Oct 2026, finding 85). Template and approved wording:
emails/spotlight_candidates_note.py.

Run inside the api container on the droplet (needs DB + mail env):

    python -m emails.send_spotlight_candidates_note                 # DRY RUN: counts only
    python -m emails.send_spotlight_candidates_note --preview TO    # one proof to TO
    python -m emails.send_spotlight_candidates_note --send          # every candidate, once

A candidate is a person who:
  - is activated and a member (service/admin/queries/members.py), never a
    staff test account;
  - passes every Spotlight eligibility rule except consent
    (service/spotlight/eligibility.featurable_sql: verified, adult, an
    approved photo, not reported, not pending deletion, not featured in the
    last 30 days);
  - was online in the last 30 days and has not opted in;
  - HAS an `e1` row in the send log. The E1 resend on Mon 19 Oct goes to the
    members who never had E1, so nobody gets both;
  - has not left campaigns, is not a suppressed address, and has never had
    this note (no `spotlight_note` row in the send log or the outbox).

Members get it through the campaign outbox, like every member email: --send
queues one row per candidate under a fixed campaign id, and the emailoutbox
cron sends it, re-checking unsubscribe and suppression at send time. A second
--send queues nobody. The note keeps its own cadence (once ever), so it is
queued exempt and listed in SELF_CAPPED_CAMPAIGNS: it neither waits behind
the weekly email nor holds the next one back.

The dry run prints counts, never an address, and writes nothing. --preview
sends exactly one proof, with a sample first name, straight to the mailer
and records nothing; it is not filtered by suppression, because the proof
usually goes to a staff inbox, and its unsubscribe link is the inert proof
placeholder, as every proof's is (scripts/send_proofs.py).
"""
from __future__ import annotations

import argparse
from typing import Optional

from emails.base import suppressed_sql_pattern
from emails.spotlight_candidates_note import SUBJECT, note_html, note_text
from service.admin.queries.members import member_sql
from service.campaigns import suppressed_predicate_sql, unsubscribed_predicate_sql
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.spotlight.eligibility import featurable_sql
from service.unsubscribe import make_url as _unsub_url

CAMPAIGN = 'spotlight_note'
CAMPAIGN_ID = 'spotlight-note-2026-10'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
FROM_NAME = "Ehud at Ahavah"
DEFAULT_REPLY_TO = f"support@{EMAIL_DOMAIN}"
SAMPLE_FIRST_NAME = "Miriam"
ONLINE_DAYS = 30

# Where a proof's unsubscribe link points (scripts/send_proofs.py): the
# proof goes to a staff inbox, and a real /u/<token> link would change that
# account's settings if clicked.
PROOF_LINK_DISABLED = 'https://ahavah.app/proof-link-disabled'

_WHERE = f"""
     WHERE p.activated AND {member_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND {featurable_sql('p')}
       AND NOT p.spotlight_opt_in
       AND p.last_online_time > NOW() - make_interval(days => {ONLINE_DAYS})
       AND EXISTS (SELECT 1 FROM email_send_log l
                    WHERE l.person_id = p.id AND l.campaign = 'e1')
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = %(c)s)
       AND NOT EXISTS (SELECT 1 FROM email_outbox ob
                        WHERE ob.person_id = p.id AND ob.campaign = %(c)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""
_Q_RECIPIENTS = f"""
    SELECT p.id AS person_id, p.email,
           NULLIF(split_part(trim(p.name), ' ', 1), '') AS first_name,
           g.name AS gender
      FROM person p LEFT JOIN gender g ON g.id = p.gender_id
    {_WHERE}
     ORDER BY p.id
"""
_Q_COUNT = f"SELECT count(*) AS n FROM person p {_WHERE}"


def _binds() -> dict:
    return dict(ex=_excluded(), sup=suppressed_sql_pattern(), c=CAMPAIGN)


def recipients() -> list[dict]:
    from database import api_tx
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(_Q_RECIPIENTS, _binds()).fetchall()]


def recipient_count() -> int:
    from database import api_tx
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_COUNT, _binds()).fetchone()['n'])


def _list_unsubscribe(url: str) -> str:
    return f"<mailto:support@{EMAIL_DOMAIN}?subject=Unsubscribe>, <{url}>"


def build_message(email: str, first: Optional[str]) -> dict:
    unsub = _unsub_url(UNSUB_SCOPE, email, WEB_BASE_URL)
    return dict(
        unsubscribe_url=unsub,
        html=note_html(first, unsub),
        text=note_text(first, unsub),
        list_unsubscribe=_list_unsubscribe(unsub),
    )


def build_for(row: dict) -> tuple[str, str, str]:
    """The runner's builder. It mints no link or token, so a dry run and a
    real run build the same thing."""
    msg = build_message(row['email'], row.get('first_name'))
    return SUBJECT, msg['html'], msg['text']


def run(*, send: bool, only_ids: Optional[list[int]] = None,
        reply_to: str = DEFAULT_REPLY_TO) -> dict:
    """Queue (or, with send False, build and count) the note for every
    candidate, through the campaign runner and the outbox."""
    from database import api_tx
    from service.campaigns.runner import audit_send, run_campaign
    rows = recipients()
    if only_ids is not None:
        rows = [r for r in rows if r['person_id'] in set(only_ids)]
    res = run_campaign(
        api_tx, CAMPAIGN, CAMPAIGN_ID, rows, build_for, send=send, from_addr=FROM_ADDR,
        unsub_scope=UNSUB_SCOPE, exempt=True, from_name=FROM_NAME, reply_to=reply_to,
        list_unsubscribe=lambda e: _list_unsubscribe(_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)))
    if send:
        with api_tx() as tx:
            audit_send(tx, 'cli', CAMPAIGN, res)
    return res


def send_preview(smtp, to: str, *, reply_to: str):
    """One proof to `to` with a sample first name. Writes nothing."""
    return smtp.send(
        subject=SUBJECT,
        body=note_html(SAMPLE_FIRST_NAME, PROOF_LINK_DISABLED),
        text_body=note_text(SAMPLE_FIRST_NAME, PROOF_LINK_DISABLED),
        to_addr=to,
        from_addr=FROM_ADDR,
        from_name=FROM_NAME,
        reply_to=reply_to,
    )


def _mailer():
    from smtp import aws_smtp
    return aws_smtp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Send the owner's note to the Spotlight candidates.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print the recipient counts (the default)")
    mode.add_argument("--preview", metavar="TO", help="send one proof to TO and record nothing")
    mode.add_argument("--send", action="store_true", help="queue the note for every candidate, once")
    ap.add_argument("--reply-to", default=DEFAULT_REPLY_TO,
                    help=f"Reply-To address (default {DEFAULT_REPLY_TO})")
    args = ap.parse_args(argv)

    print(f"Subject: {SUBJECT!r}  From: {FROM_NAME} <{FROM_ADDR}>  Reply-To: {args.reply_to}")

    if args.preview:
        print("Sending one proof (sample first name, nothing recorded) ...")
        message_id = send_preview(_mailer(), args.preview, reply_to=args.reply_to)
        print(f"done (message id: {message_id or 'none returned'}).")
        return

    if not args.send:
        rows = recipients()
        for row in rows:
            build_for(row)
        women = sum(1 for r in rows if r['gender'] == 'Woman')
        named = sum(1 for r in rows if r['first_name'])
        print(f"DRY RUN: {len(rows)} candidate(s) ({women} women, {len(rows) - women} others); "
              f"{named} with a first name; every message built, nothing written.")
        print("Re-run with --preview TO for a proof, or --send to queue it.")
        return

    res = run(send=True, reply_to=args.reply_to)
    print(f"done: {res['queued']} queued, {res['skipped_unsubscribed']} unsubscribed, "
          f"{res['skipped_suppressed']} suppressed, {res['skipped_cap']} already queued"
          + (f"; stopped on an error: {res['error']}" if res.get('error') else "")
          + ". The emailoutbox cron sends them.")


if __name__ == "__main__":
    main()
