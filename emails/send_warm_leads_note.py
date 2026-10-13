"""One-off: the owner's personal note to the warm leads (health review,
13 Oct 2026, finding 48). Template and approved wording: emails/warm_leads_note.py.

Run inside the api container on the droplet (needs DB + mail env):

    python -m emails.send_warm_leads_note                     # DRY RUN: counts only
    python -m emails.send_warm_leads_note --preview TO        # one proof to TO
    python -m emails.send_warm_leads_note --send              # every warm lead, once

A warm lead is an address in waitlist_signup or beta_signup that:
  - has no `person` row (compared lower-cased against person.email and
    person.normalized_email, and on the address normalised the way sign-up
    normalises it, so a Gmail dot or plus variant of an account counts as
    that account);
  - is unsubscribed in neither lead table that holds it;
  - is not a suppressed or sample address (emails.base).
An address on both lists is one lead. Its unsubscribe link uses the waitlist
scope when it has a waitlist row, otherwise the beta scope, the same scopes
the existing lead emails print.

The dry run prints counts, never an address. --preview sends exactly one
proof, with a sample first name, and records nothing against any lead; it
is not filtered by suppression, because the proof usually goes to a staff
inbox. --send records each address in lead_email_send (migration 0063)
before it calls the mailer, so a second --send emails nobody twice. A send
the mailer did not confirm keeps its row and is reported, not retried.
"""
from __future__ import annotations

import argparse
import time
from typing import Callable, Iterable

from antiabuse.antispam.signupemail import normalize_email
from emails.base import is_suppressed_send, mask_email, suppressed_sql_pattern
from emails.warm_leads_note import SUBJECT, note_html, note_text
from service.admin.queries.members import member_sql
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.unsubscribe import make_url as _unsub_url

CAMPAIGN = "warm_leads_note_2026_10"
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
FROM_NAME = "Ehud at Ahavah"
DEFAULT_REPLY_TO = f"support@{EMAIL_DOMAIN}"
SAMPLE_FIRST_NAME = "Miriam"

# Resend's default API limit is 2 requests a second. One send every 0.6s
# stays under it, and Smtp.send backs off and retries on a 429 regardless.
DEFAULT_PAUSE_SECONDS = 0.6

# Keys a stored answers blob might carry a name under. The waitlist wizard
# collected no name as of 13 Oct 2026, so today every greeting falls back
# to "Shalom,"; the lookup is here so a future name field is used.
_NAME_KEYS = ("first_name", "firstName", "given_name", "name")


_Q_LEADS = """
    SELECT email,
           bool_or(src = 'waitlist') AS on_waitlist,
           (array_agg(answers) FILTER (WHERE src = 'waitlist'))[1] AS answers
      FROM (
        SELECT lower(trim(email)) AS email, 'waitlist' AS src,
               unsubscribed_at, answers
          FROM waitlist_signup
        UNION ALL
        SELECT lower(trim(email)), 'beta', unsubscribed_at, NULL::jsonb
          FROM beta_signup
      ) leads
     WHERE email LIKE '%%_@_%%'
       AND NOT (email ILIKE ANY(%(suppressed)s))
       AND NOT EXISTS (
             SELECT 1 FROM person p
              WHERE lower(p.email) = leads.email
                 OR lower(p.normalized_email) = leads.email)
     GROUP BY email
    HAVING bool_and(unsubscribed_at IS NULL)
     ORDER BY email
"""

_Q_ACCOUNT_ADDRESSES = """
    SELECT lower(email) AS a FROM person WHERE email IS NOT NULL
    UNION
    SELECT lower(normalized_email) FROM person WHERE normalized_email IS NOT NULL
"""

_Q_MEMBERS = f"""
    SELECT count(*) AS n FROM person p
     WHERE p.activated AND {member_sql('p')}
"""

_Q_ALREADY = """
    SELECT email FROM lead_email_send
     WHERE campaign = %(campaign)s AND email = ANY(%(emails)s)
"""

# Outbox claim: the row is committed before the mailer is called, so a crash
# or a second run cannot email this address again. Returns a row only for
# the run that won the claim.
_Q_CLAIM = """
    INSERT INTO lead_email_send (email, campaign)
    VALUES (%(email)s, %(campaign)s)
    ON CONFLICT (email, campaign) DO NOTHING
    RETURNING email
"""

_Q_MARK_SENT = """
    UPDATE lead_email_send
       SET message_id = %(message_id)s, sent_at = NOW()
     WHERE email = %(email)s AND campaign = %(campaign)s
"""


def first_name(answers) -> str | None:
    """The lead's first name from its stored answers, or None."""
    if not isinstance(answers, dict):
        return None
    for key in _NAME_KEYS:
        value = answers.get(key)
        if isinstance(value, str) and value.strip():
            word = value.strip().split()[0]
            return word[:1].upper() + word[1:]
    return None


def member_count(tx) -> int:
    """N: activated members, never an admin-role account (the dashboard's
    member rule, service/admin/queries/members.py)."""
    return tx.execute(_Q_MEMBERS).fetchone()["n"]


def eligible_leads(tx) -> list[dict]:
    """Every warm lead, once: dict(email, first_name, scope)."""
    rows = tx.execute(_Q_LEADS, dict(suppressed=suppressed_sql_pattern())).fetchall()
    accounts = {r["a"] for r in tx.execute(_Q_ACCOUNT_ADDRESSES).fetchall()}
    leads = []
    for row in rows:
        email = row["email"]
        if is_suppressed_send(email):
            continue
        if email in accounts or (normalize_email(email) or "").lower() in accounts:
            continue
        leads.append(dict(
            email=email,
            first_name=first_name(row["answers"]),
            scope="waitlist" if row["on_waitlist"] else "beta",
        ))
    return leads


def already_sent(tx, emails: Iterable[str]) -> set[str]:
    rows = tx.execute(_Q_ALREADY, dict(campaign=CAMPAIGN, emails=list(emails))).fetchall()
    return {r["email"] for r in rows}


def build_message(email: str, first: str | None, n: int, scope: str) -> dict:
    unsub = _unsub_url(scope, email, WEB_BASE_URL)
    return dict(
        unsubscribe_url=unsub,
        html=note_html(first, n, unsub),
        text=note_text(first, n, unsub),
        list_unsubscribe=f"<mailto:support@{EMAIL_DOMAIN}?subject=Unsubscribe>, <{unsub}>",
    )


def _send_one(smtp, to: str, first: str | None, n: int, scope: str, reply_to: str):
    msg = build_message(to, first, n, scope)
    return smtp.send(
        subject=SUBJECT,
        body=msg["html"],
        text_body=msg["text"],
        to_addr=to,
        from_addr=FROM_ADDR,
        from_name=FROM_NAME,
        reply_to=reply_to,
        list_unsubscribe=msg["list_unsubscribe"],
    )


def send_preview(smtp, to: str, n: int, *, reply_to: str):
    """One proof to `to` with a sample first name. Writes nothing."""
    return _send_one(smtp, to, SAMPLE_FIRST_NAME, n, "waitlist", reply_to)


def send_all(tx_factory, smtp, leads: list[dict], n: int, *, reply_to: str,
             pause: float = DEFAULT_PAUSE_SECONDS,
             sleep: Callable[[float], None] = time.sleep) -> dict:
    """Send the note to each lead not already in the log. Returns counts."""
    result = dict(sent=0, unconfirmed=0, already_sent=0, skipped_suppressed=0)
    first_send = True
    for lead in leads:
        email = lead["email"]
        if is_suppressed_send(email):
            result["skipped_suppressed"] += 1
            continue
        with tx_factory() as tx:
            claimed = tx.execute(_Q_CLAIM, dict(email=email, campaign=CAMPAIGN)).fetchone()
        if not claimed:
            result["already_sent"] += 1
            continue

        if not first_send and pause:
            sleep(pause)
        first_send = False

        try:
            message_id = _send_one(smtp, email, lead["first_name"], n, lead["scope"], reply_to)
        except Exception as exc:
            # Claimed and possibly sent: keep the claim so no one is mailed
            # twice, and report it.
            print(f"   unconfirmed {mask_email(email)}: {exc!r}")
            result["unconfirmed"] += 1
            continue
        if not message_id:
            # Smtp.send returns None when every retry failed on the Resend
            # path (and on the plain SMTP path even on success). Either way
            # the outcome is unknown, so the claim stays.
            print(f"   unconfirmed {mask_email(email)}: the mailer returned no message id")
            result["unconfirmed"] += 1
            continue
        with tx_factory() as tx:
            tx.execute(_Q_MARK_SENT, dict(email=email, campaign=CAMPAIGN, message_id=message_id))
        result["sent"] += 1
        print(f"   sent {mask_email(email)}")
    return result


def _mailer():
    from smtp import aws_smtp
    return aws_smtp


def main(argv: list[str] | None = None) -> None:
    from database import api_tx

    ap = argparse.ArgumentParser(description="Send the owner's note to the warm leads.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print the recipient count and N (the default)")
    mode.add_argument("--preview", metavar="TO", help="send one proof to TO and record nothing")
    mode.add_argument("--send", action="store_true", help="send to every warm lead, once")
    ap.add_argument("--reply-to", default=DEFAULT_REPLY_TO,
                    help=f"Reply-To address (default {DEFAULT_REPLY_TO})")
    ap.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
                    help="seconds between sends (default %(default)s)")
    args = ap.parse_args(argv)

    with api_tx() as tx:
        n = member_count(tx)
        leads = eligible_leads(tx)
        done = already_sent(tx, [lead["email"] for lead in leads])

    print(f"Subject: {SUBJECT!r}  From: {FROM_NAME} <{FROM_ADDR}>  Reply-To: {args.reply_to}")
    print(f"N = {n} (activated members, admin accounts excluded)")

    if args.preview:
        print("Sending one proof (sample first name, nothing recorded) ...")
        message_id = send_preview(_mailer(), args.preview, n, reply_to=args.reply_to)
        print(f"done (message id: {message_id or 'none returned'}).")
        return

    to_send = [lead for lead in leads if lead["email"] not in done]
    named = sum(1 for lead in to_send if lead["first_name"])
    if not args.send:
        print(f"DRY RUN: {len(leads)} warm lead(s); {len(done)} already sent; "
              f"{len(to_send)} to send ({named} with a first name).")
        print("Re-run with --preview TO for a proof, or --send to send.")
        return

    print(f"Sending to {len(to_send)} warm lead(s) ...")
    result = send_all(api_tx, _mailer(), to_send, n, reply_to=args.reply_to, pause=args.pause)
    print(f"done: {result['sent']} sent, {result['unconfirmed']} unconfirmed, "
          f"{result['already_sent']} already sent, {result['skipped_suppressed']} suppressed.")

    from service.campaigns.runner import SEND_AUDIT_ACTION
    from service.admin import record_system_audit
    with api_tx() as tx:
        record_system_audit(tx, "cli", SEND_AUDIT_ACTION,
                            metadata=dict(campaign=CAMPAIGN, n=n, **result))


if __name__ == "__main__":
    main()
