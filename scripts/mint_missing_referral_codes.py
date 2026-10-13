"""Mint a personal referral code for every member who has none.

    PYTHONPATH=/app python3 scripts/mint_missing_referral_codes.py [--dry-run]

Health review, 13 Oct 2026 (finding 77): 4 members who joined on 16 and
17 June had no `person.referral_code`. Three fell back to a beta-era code
on /invite; one had none, so the screen showed a link with no code. Codes
are minted at finish-onboarding (since migration 0037) and, from this
deploy, by GET /referrals/me for anyone who still has none. This mints
them for the members now, with the same `mint_person_code`.

Members only: staff accounts are left alone and only counted (2 on
13 Oct); one of them gets a code if they ever open /invite. A beta-era
code a member already shared keeps working; /invite shows the new code.

Idempotent: a second run mints nothing. Prints counts only.
"""
from __future__ import annotations

import argparse

from database import api_tx
from service.admin.queries.members import member_sql
from service.referrals import mint_person_code

_Q_WITHOUT_CODE = f"""
    SELECT p.id, {member_sql('p')} AS is_member
      FROM person p
     WHERE p.referral_code IS NULL
     ORDER BY p.id
"""


def mint_missing(tx, dry_run: bool = False) -> dict:
    """On a dry run, `would_mint`; on a real run, `minted`. Both carry
    `staff_without_code`, the staff accounts left alone."""
    rows = tx.execute(_Q_WITHOUT_CODE).fetchall()
    members = [r['id'] for r in rows if r['is_member']]
    out = dict(staff_without_code=len(rows) - len(members))
    if dry_run:
        return dict(out, would_mint=len(members))
    minted = sum(1 for pid in members if mint_person_code(tx, pid))
    return dict(out, minted=minted)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    with api_tx() as tx:
        out = mint_missing(tx, dry_run=a.dry_run)
    if a.dry_run:
        print(f"would mint a referral code for {out['would_mint']} member(s); "
              f"{out['staff_without_code']} staff account(s) without one left alone")
        print('dry run, nothing written')
    else:
        print(f"minted a referral code for {out['minted']} member(s); "
              f"{out['staff_without_code']} staff account(s) without one left alone")


if __name__ == '__main__':
    main()
