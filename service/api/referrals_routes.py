"""Public + authed referral routes.

  GET /referrals/me — authed, returns the caller's code + counters.

Phase-2 surface. The public POST /referrals/code (for the pre-launch
<ReferralCard>) is intentionally NOT shipped here; Phase 1's email
blast covers the introduction. Add it later if a UI surface is built.
"""
from __future__ import annotations

import duotypes as t
from service.api.decorators import aget
from database import api_tx
from service.referrals import get_my_referrals


@aget("/referrals/me")
def get_referrals_me(s: t.SessionInfo):
    """Full invite-screen contract; see service.referrals.get_my_referrals.

    READ COMMITTED because the first load mints the member's code. Two
    first loads at once under REPEATABLE READ: the second one's UPDATE hit
    a serialisation error on every retry and the route answered 500 with
    ReferralCodeCollision. Under READ COMMITTED it waits for the first,
    matches no row (the code is no longer NULL) and reads the stored code
    back."""
    with api_tx('READ COMMITTED') as tx:
        return get_my_referrals(tx, s.person_uuid)
