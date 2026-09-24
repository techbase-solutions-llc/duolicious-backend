"""Engagement tab data: what members do with each other.

One route, one transaction. The queries and the reasoning behind them live
in `service/admin/queries/engagement.py`; read that before changing this.

Nothing here reads message content, by the owner's instruction and by a test
that enforces it.
"""
from __future__ import annotations

import duotypes as t

from database import api_tx
from service.admin import require_admin
from service.admin.queries.engagement import Q_ENGAGEMENT_KPIS
from service.api.decorators import aget


@aget('/admin/engagement')
def get_admin_engagement(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        kpis = tx.execute(Q_ENGAGEMENT_KPIS).fetchone() or {}
    return dict(kpis=dict(kpis))
