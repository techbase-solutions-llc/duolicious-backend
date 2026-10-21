"""Cohorts tab — waitlist / beta / referrals sub-routes."""
from __future__ import annotations

import duotypes as t

from service.api.decorators import aget
from service.admin import require_admin
from service.admin.queries import (
    Q_WAITLIST_KPIS, Q_WAITLIST_VELOCITY_30D,
    Q_WAITLIST_SEX, Q_WAITLIST_INTENT, Q_WAITLIST_COUNTRY,
    Q_WAITLIST_ETHNICITY, Q_WAITLIST_ASSEMBLY, Q_WAITLIST_SOURCE,
    Q_BETA_KPIS, Q_BETA_ROWS, Q_BETA_FUNNEL,
    Q_REFERRALS_KPIS, Q_REFERRALS_CLICK_STREAM_7D, Q_REFERRALS_PER_INVITER,
)
from database import api_tx
from service.api.admin.overview_routes import _empty_when_nothing


@aget('/admin/cohorts/waitlist')
def get_cohorts_waitlist(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        kpis = tx.execute(Q_WAITLIST_KPIS).fetchone() or {}
        # No rows when nothing happened, as on the Overview, so the admin's
        # empty state can show (TEC-1845 admin audit, Minor 30).
        velocity = _empty_when_nothing(
            [dict(r) for r in tx.execute(Q_WAITLIST_VELOCITY_30D).fetchall()],
            ('waitlist', 'beta', 'person'))
        sex = [dict(r) for r in tx.execute(Q_WAITLIST_SEX).fetchall()]
        intent = [dict(r) for r in tx.execute(Q_WAITLIST_INTENT).fetchall()]
        country = [dict(r) for r in tx.execute(Q_WAITLIST_COUNTRY).fetchall()]
        ethnicity = [dict(r) for r in tx.execute(Q_WAITLIST_ETHNICITY).fetchall()]
        assembly = [dict(r) for r in tx.execute(Q_WAITLIST_ASSEMBLY).fetchall()]
        source = [dict(r) for r in tx.execute(Q_WAITLIST_SOURCE).fetchall()]
    return {
        'kpis': dict(kpis),
        'velocity_30d': velocity,
        'breakdowns': {
            'sex': sex, 'intent': intent, 'country': country,
            'ethnicity': ethnicity, 'assembly': assembly, 'source': source,
        },
    }


@aget('/admin/cohorts/beta')
def get_cohorts_beta(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        kpis = tx.execute(Q_BETA_KPIS).fetchone() or {}
        rows = [dict(r) for r in tx.execute(Q_BETA_ROWS).fetchall()]
        funnel = tx.execute(Q_BETA_FUNNEL).fetchone() or {}
    return {
        'kpis': dict(kpis),
        'rows': rows,
        'funnel': dict(funnel),
    }


@aget('/admin/cohorts/referrals')
def get_cohorts_referrals(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        kpis = tx.execute(Q_REFERRALS_KPIS).fetchone() or {}
        click_stream = _empty_when_nothing(
            [dict(r) for r in tx.execute(Q_REFERRALS_CLICK_STREAM_7D).fetchall()],
            ('mobile', 'desktop', 'bot'))
        per_inviter = [dict(r) for r in tx.execute(Q_REFERRALS_PER_INVITER).fetchall()]
    return {
        'kpis': dict(kpis),
        'click_stream_7d': click_stream,
        'per_inviter': per_inviter,
    }
