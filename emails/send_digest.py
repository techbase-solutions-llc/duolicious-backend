"""Community digest to every activated member.

Superseded by send_community_weekly on 2026-09-13; kept for one release,
do not schedule.

Stats come straight from the database at send time: activated member
count (excluding the admin account), first names of members who joined
in the last NEW_WINDOW_DAYS days, and the all-time match count. New
members themselves are excluded from the recipient list only if they
joined today (they know they joined; everyone else is greeted with
their arrival).

    python -m emails.send_digest                   # DRY RUN
    python -m emails.send_digest --preview a@b.com # rendered copy to one address
    python -m emails.send_digest --send            # send to all members
"""
from __future__ import annotations

import argparse

from database import api_tx
from emails.base import is_suppressed_send, mask_email
from emails.digest import digest_html, subject_for, FROM_ADDR
from service.campaigns import unsubscribed_predicate_sql
from service.config import WEB_BASE_URL
from service.unsubscribe import make_url as _unsub_url
from smtp import make_aws_smtp

NEW_WINDOW_DAYS = 14

_Q_STATS = """
    SELECT
        (SELECT count(*) FROM person
          WHERE activated AND email <> 'admin@ahavah.app') AS total_members,
        (SELECT count(*) FROM ahavah_match) AS total_matches
"""

_Q_NEW = """
    SELECT name FROM person
    WHERE activated
      AND email <> 'admin@ahavah.app'
      AND sign_up_time > NOW() - make_interval(days => %(days)s)
    ORDER BY sign_up_time ASC
"""

# Campaign mail carries the `campaigns` unsubscribe scope (finding 62):
# the `notifications` scope would also silence like, match and message
# emails. Members who left campaigns are not selected.
UNSUB_SCOPE = 'campaigns'

_Q_RECIPIENTS = f"""
    SELECT p.email, p.name FROM person p
    WHERE p.activated AND p.email <> 'admin@ahavah.app'
      AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
    ORDER BY p.email
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    ap.add_argument("--preview", metavar="EMAIL",
                    help="send the rendered digest to this address only")
    args = ap.parse_args()

    with api_tx() as tx:
        stats = tx.execute(_Q_STATS).fetchone()
        new_names = [r["name"] for r in
                     tx.execute(_Q_NEW, dict(days=NEW_WINDOW_DAYS)).fetchall()]
        recipients = tx.execute(_Q_RECIPIENTS).fetchall()

    if not new_names:
        print("no new members in the window, nothing to announce")
        return

    subject = subject_for(len(new_names))
    smtp = make_aws_smtp()

    if args.preview:
        unsub = _unsub_url(UNSUB_SCOPE, args.preview, WEB_BASE_URL)
        smtp.send(
            subject=f"[PREVIEW] {subject}",
            body=digest_html(
                new_names, stats["total_members"], stats["total_matches"], unsub),
            to_addr=args.preview,
            from_addr=FROM_ADDR,
        )
        print(f"preview sent to {args.preview} "
              f"({len(new_names)} new, {stats['total_members']} total, "
              f"{stats['total_matches']} matches)")
        return

    sent = skipped = 0
    for row in recipients:
        email = row["email"]
        if is_suppressed_send(email):
            skipped += 1
            continue
        if not args.send:
            print(f"DRY RUN {mask_email(email)}")
            sent += 1
            continue
        unsub = _unsub_url(UNSUB_SCOPE, email, WEB_BASE_URL)
        smtp.send(
            subject=subject,
            body=digest_html(
                new_names, stats["total_members"], stats["total_matches"], unsub),
            to_addr=email,
            from_addr=FROM_ADDR,
            list_unsubscribe=f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{unsub}>",
        )
        print(f"sent to {mask_email(email)}")
        sent += 1

    mode = "SENT" if args.send else "DRY RUN"
    print(f"{mode}: {sent} recipient(s), {skipped} suppressed | "
          f"{len(new_names)} new members, {stats['total_members']} total, "
          f"{stats['total_matches']} matches")


if __name__ == "__main__":
    main()
