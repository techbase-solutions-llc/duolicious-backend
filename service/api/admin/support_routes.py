"""Admin > Support: the copy of support@ahavah.app (TEC-2115,
docs/plans/2026-11-05-support-messages-in-admin.md).

  GET  /admin/support/messages?status=open|handled|not_for_us&page=N
       50 a page; open oldest first, the rest newest first
  GET  /admin/support/summary
       the counts by status and the inbox status only, no message: the
       admin's badge polls it every minute on every screen
  POST /admin/support/messages/<id>/handled
  POST /admin/support/messages/<id>/not-for-us
  POST /admin/support/messages/<id>/reopen     a mark made by mistake

Admin only, as every /admin route, under the default rate limit. Only an
open message can be marked; a second attempt answers 409. Only a handled or
not-for-us message can be reopened; an open one answers 409. Each mark writes
an audit row in its own transaction, naming the message id and the member,
never the address or the text.
"""
from __future__ import annotations

import duotypes as t
import psycopg
from flask import abort, request

from database import api_tx
from service import support_inbox
from service.admin import int_arg, record_audit, require_admin
from service.api.decorators import aget, apost
from service.support_inbox import admin as support


def _already_handled(status: str):
    return dict(error='already_handled', status=status), 409


@aget('/admin/support/messages')
def get_admin_support_messages(s: t.SessionInfo):
    require_admin(s)
    status = request.args.get('status') or None
    if status is not None and status not in support.SUPPORT_STATUSES:
        abort(400)
    page = int_arg('page', 1, 1, 100_000)
    with api_tx('read committed') as tx:
        return support.list_messages(tx, status=status, page=page,
                                     enabled=support_inbox.enabled())


@aget('/admin/support/summary')
def get_admin_support_summary(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return support.summary(tx, enabled=support_inbox.enabled())


def _mark(s: t.SessionInfo, mid: int, status: str, action: str):
    require_admin(s)
    try:
        with api_tx('read committed') as tx:
            out = support.mark(tx, mid, status, handled_by=s.email)
            record_audit(tx, s, action, target_uuid=out.pop('member_uuid'),
                         metadata=dict(support_message_id=mid))
    except support.MessageNotFound:
        abort(404)
    except support.AlreadyHandled as e:
        return _already_handled(e.status)
    except psycopg.errors.SerializationFailure:
        return _already_handled('unknown')
    return out


@apost('/admin/support/messages/<int:mid>/handled')
def post_admin_support_handled(s: t.SessionInfo, mid: int):
    return _mark(s, mid, 'handled', 'support_handled')


@apost('/admin/support/messages/<int:mid>/not-for-us')
def post_admin_support_not_for_us(s: t.SessionInfo, mid: int):
    return _mark(s, mid, 'not_for_us', 'support_not_for_us')


@apost('/admin/support/messages/<int:mid>/reopen')
def post_admin_support_reopen(s: t.SessionInfo, mid: int):
    require_admin(s)
    try:
        with api_tx('read committed') as tx:
            out = support.reopen(tx, mid)
            record_audit(tx, s, 'support_reopened', target_uuid=out['member_uuid'],
                         metadata=dict(support_message_id=mid, previous=out['previous']))
    except support.MessageNotFound:
        abort(404)
    except support.AlreadyOpen:
        return dict(error='already_open'), 409
    except psycopg.errors.SerializationFailure:
        return dict(error='already_open'), 409
    return dict(id=out['id'], status=out['status'])
