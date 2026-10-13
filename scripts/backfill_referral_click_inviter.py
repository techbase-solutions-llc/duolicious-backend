"""Give past referral link clicks the inviter the logger missed.

    PYTHONPATH=/app python3 scripts/backfill_referral_click_inviter.py [--dry-run]

Health review, 13 Oct 2026 (findings 7, 25, 73): until then the click
logger (service/api/referral_click_route.py) looked a code up in
beta_signup only. Every member's own invite link carries person.referral_code,
which is never in beta_signup, so every click on one was stored with no
inviter: 87 of 128 clicks, 9 Aug to 23 Sep, 81 of them on one member's link.

This fills `inviter_email` on those rows by the rule the logger now uses
(service.referrals.inviter_email_for_code): a member's code first, then a
beta-era code. A malformed code is left alone, as the logger leaves it, and
so is a code nobody holds.

Idempotent: it only touches rows with no inviter, so a second run finds
nothing. Prints counts only, never an address.
"""
from __future__ import annotations

import argparse

from database import api_tx

# Person first, then beta_signup: the order of `_Q_INVITER_FROM_CODE` in
# service/referrals/__init__.py. Both columns carry a unique index, so each
# subquery returns at most one row.
_RESOLVED = """
    SELECT c.id,
           (SELECT email FROM person      WHERE referral_code = c.code) AS member_email,
           (SELECT email FROM beta_signup WHERE referral_code = c.code) AS beta_email
      FROM referral_link_click c
     WHERE c.inviter_email IS NULL AND c.well_formed
"""

_Q_COUNT = f"""
    WITH resolved AS ({_RESOLVED})
    SELECT count(*) FILTER (WHERE member_email IS NOT NULL)                       AS member_codes,
           count(*) FILTER (WHERE member_email IS NULL AND beta_email IS NOT NULL) AS beta_codes,
           count(*) FILTER (WHERE member_email IS NULL AND beta_email IS NULL)     AS no_holder
      FROM resolved
"""

_Q_FILL = f"""
    WITH resolved AS ({_RESOLVED})
    UPDATE referral_link_click c
       SET inviter_email = COALESCE(r.member_email, r.beta_email)
      FROM resolved r
     WHERE c.id = r.id AND COALESCE(r.member_email, r.beta_email) IS NOT NULL
    RETURNING r.member_email IS NOT NULL AS on_member_code
"""


def backfill(tx, dry_run: bool = False) -> dict:
    """Counts of clicks with no inviter, by who holds the code. On a real
    run `member_codes` and `beta_codes` are the rows filled."""
    counts = dict(tx.execute(_Q_COUNT).fetchone())
    if dry_run:
        return counts
    filled = [r['on_member_code'] for r in tx.execute(_Q_FILL).fetchall()]
    return dict(member_codes=sum(1 for m in filled if m),
                beta_codes=sum(1 for m in filled if not m),
                no_holder=counts['no_holder'])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    with api_tx() as tx:
        out = backfill(tx, dry_run=a.dry_run)
    verb = 'would fill' if a.dry_run else 'filled'
    print(f"{verb} {out['member_codes']} click(s) on member codes and "
          f"{out['beta_codes']} on beta codes; {out['no_holder']} have a code nobody holds")
    if a.dry_run:
        print('dry run, nothing written')


if __name__ == '__main__':
    main()
