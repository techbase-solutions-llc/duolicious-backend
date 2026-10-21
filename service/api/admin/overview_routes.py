"""Overview tab routes.

GET /admin/whoami — { is_admin, email, person_uuid, roles }. Returns 200
even for non-admins (so the FE can render the Unauthorized screen
without first hitting a 403). Other handlers in this module call
require_admin and return 403 for non-admins."""
from __future__ import annotations

import duotypes as t

from service.api.decorators import aget
from service.admin import is_admin, require_admin
from service.admin.queries import (
    Q_OVERVIEW_KPIS,
    Q_OVERVIEW_SIGNUPS_30D,
    Q_OVERVIEW_REFERRAL_CTR_7D,
    Q_OVERVIEW_PREMIUM_30D,
    Q_OVERVIEW_MEMBERS_30D,
    Q_OVERVIEW_RECENT_ACTIVITY,
)
from service.admin.queries.overview import (
    Q_OVERVIEW_MEMBER_TOTAL, Q_OVERVIEW_RECENT_ACTIVITY_ALL)
from service.growth.queries import _excluded
from database import api_tx


def _empty_when_nothing(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """A chart with nothing in it arrives as no rows.

    Every series is a generate_series of days, so it always had 30 or 7
    rows, and the admin's empty state (shown on `length === 0`) could never
    appear: Premium adds drew 30 zero-height bars instead of saying nothing
    had happened. A series with any value keeps every day, so the axis is
    whole."""
    return rows if any(r[k] for r in rows for k in keys) else []


_Q_STAFF_ROLES = """
    SELECT ARRAY(SELECT r FROM unnest(COALESCE(roles, ARRAY[]::text[])) r
                  WHERE r IN ('admin', 'mod') ORDER BY r) AS roles
      FROM person WHERE uuid = %(uuid)s
"""


# A signed-in onboardee (a code that is valid for an address with no
# member) is answered is_admin false rather than 401, so the admin sends
# them to the unauthorised screen instead of saying the code was not
# accepted (TEC-1845 admin audit, Minor 27). Sign-in is still required.
@aget('/admin/whoami', expected_onboarding_status=None)
def get_admin_whoami(s: t.SessionInfo):
    if not s or not s.person_uuid:
        return {'is_admin': False, 'email': None, 'person_uuid': None, 'roles': []}
    with api_tx('read committed') as tx:
        admin = is_admin(tx, s.person_uuid)
        row = tx.execute(_Q_STAFF_ROLES, dict(uuid=s.person_uuid)).fetchone()
    # The caller's staff roles (TEC-1845 admin audit), so an admin can route
    # a mod to a view of their own. Only admin and mod are ever sent.
    return {
        'is_admin': admin,
        'email': s.email if admin else None,
        'person_uuid': s.person_uuid if admin else None,
        'roles': list(row['roles']) if row else [],
    }


@aget('/admin/overview')
def get_admin_overview(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        kpis = dict(tx.execute(Q_OVERVIEW_KPIS).fetchone() or {})
        kpis.update(tx.execute(Q_OVERVIEW_MEMBER_TOTAL, dict(ex=_excluded())).fetchone())
        signups_30d = [dict(r) for r in tx.execute(Q_OVERVIEW_SIGNUPS_30D).fetchall()]
        referral_ctr_7d = [dict(r) for r in tx.execute(Q_OVERVIEW_REFERRAL_CTR_7D).fetchall()]
        premium_30d = [dict(r) for r in tx.execute(Q_OVERVIEW_PREMIUM_30D).fetchall()]
        members_30d = [dict(r) for r in tx.execute(Q_OVERVIEW_MEMBERS_30D).fetchall()]
        recent = [dict(r) for r in tx.execute(Q_OVERVIEW_RECENT_ACTIVITY).fetchall()]
        recent_all = [dict(r) for r in tx.execute(Q_OVERVIEW_RECENT_ACTIVITY_ALL).fetchall()]
    return {
        'kpis': dict(kpis),
        'signups_30d': _empty_when_nothing(signups_30d, ('waitlist', 'beta', 'person')),
        'referral_ctr_7d': _empty_when_nothing(referral_ctr_7d, ('clicks', 'signups')),
        'premium_30d': _empty_when_nothing(premium_30d, ('adds',)),
        # Sparklines, one per KPI card that has a history to draw: Total
        # persons reads members_30d, Signups today the person column of
        # signups_30d, Referral signups 7d the signups column of
        # referral_ctr_7d, Paying members premium_30d. Active 24h has none:
        # only each member's latest time online is stored.
        'members_30d': _empty_when_nothing(members_30d, ('total',)),
        'recent_activity': recent,
        # With reports and Premium (TEC-1845 admin audit); see the query.
        'recent_activity_all': recent_all,
    }
