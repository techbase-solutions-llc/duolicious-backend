"""Audit log tab — filterable view of every destructive admin action."""
from __future__ import annotations

import duotypes as t
from flask import request

from service.api.decorators import aget
from service.admin import MAX_DAYS, MAX_PAGE, int_arg, require_admin
from service.admin.queries import Q_AUDIT_LIST, Q_AUDIT_COUNT
from service.admin.queries.audit import Q_AUDIT_ACTIONS, Q_AUDIT_ACTORS
from database import api_tx


_PAGE_SIZE = 50


@aget('/admin/audit-log')
def get_audit_log(s: t.SessionInfo):
    require_admin(s)
    actor = (request.args.get('actor') or '').strip()
    target = (request.args.get('target') or '').strip()
    action = (request.args.get('action') or '').strip()
    page = int_arg('page', 1, 1, MAX_PAGE)
    # 0 is all time (TEC-1845 admin audit). With no days the route still
    # reads the last 30, which the live admin expects.
    days = int_arg('days', 30, 0, MAX_DAYS)
    escaped = target.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    params = {
        'actor': actor, 'target': target, 'target_like': f'%{escaped}%',
        'action': action, 'days': days,
        'limit': _PAGE_SIZE, 'offset': (page - 1) * _PAGE_SIZE,
    }
    with api_tx('read committed') as tx:
        rows = [dict(r) for r in tx.execute(Q_AUDIT_LIST, params).fetchall()]
        total_row = tx.execute(Q_AUDIT_COUNT, params).fetchone()
        actors = [r['actor_email'] for r in tx.execute(Q_AUDIT_ACTORS).fetchall()]
        actions = [r['action'] for r in tx.execute(Q_AUDIT_ACTIONS).fetchall()]
    return {
        'rows': rows,
        'total': int(total_row['total']) if total_row else 0,
        'page': page,
        'page_size': _PAGE_SIZE,
        'days': days,
        'actors': actors,
        'actions': actions,
    }
