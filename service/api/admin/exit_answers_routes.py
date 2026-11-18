"""System tab, Why members left (TEC-2158).

  GET /admin/exit-answers   counts per reason (all time, last 90 days), how
                            many answers are still waiting on the 7 days,
                            and the latest 50 answers

Admin only. Nothing in the answer names a member: no id, name, email or
exact date. See service/admin/queries/exit_answers.py.
"""
from __future__ import annotations

import duotypes as t

from database import api_tx
from service.admin import require_admin
from service.admin.queries import exit_answers as queries
from service.api.decorators import aget


@aget('/admin/exit-answers')
def get_admin_exit_answers(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return queries.exit_answers(tx)
