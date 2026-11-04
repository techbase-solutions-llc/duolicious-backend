"""System tab, Feedback panel (report rewards plan, 3 Nov 2026, TEC-2025).

  GET  /admin/system/feedback?status=new|fixed|not_a_fault   newest first, 50
  POST /admin/system/feedback/<id>/fixed        {notice_line, reward}
  POST /admin/system/feedback/<id>/not-a-fault

Admin only, as every /admin/system route. Only a report still `new` can be
handled; a second attempt answers 409 and pays nothing. See
service/feedback/rewards.py for the reward and the notice.
"""
from __future__ import annotations

import duotypes as t
import psycopg
from flask import abort, request

from database import api_tx
from service.admin import record_audit, require_admin
from service.api.decorators import aget, apost, validate
from service.feedback import rewards


def _already_handled(status: str):
    return dict(error='already_handled', status=status), 409


@aget('/admin/system/feedback')
def get_admin_feedback(s: t.SessionInfo):
    require_admin(s)
    status = request.args.get('status') or None
    if status is not None and status not in rewards.FEEDBACK_STATUSES:
        abort(400)
    with api_tx('read committed') as tx:
        return rewards.list_feedback(tx, status=status)


@apost('/admin/system/feedback/<int:fid>/fixed')
@validate(t.PostFeedbackFixed)
def post_admin_feedback_fixed(req: t.PostFeedbackFixed, s: t.SessionInfo, fid: int):
    require_admin(s)
    try:
        line = rewards.clean_notice_line(req.notice_line)
    except rewards.BadNoticeLine as e:
        return dict(error='bad_notice_line', detail=str(e)), 400
    try:
        # READ COMMITTED: the row lock in mark_fixed waits for a concurrent
        # handler, then reads its committed status and refuses.
        with api_tx('read committed') as tx:
            out = rewards.mark_fixed(tx, fid, notice_line=line, reward=req.reward,
                                     handled_by=s.email)
            record_audit(tx, s, 'feedback_fixed', metadata=dict(
                feedback_id=fid, outcome=out['outcome'], member=out['member'],
                reward_tokens=out['reward_tokens'], reward_days=out['reward_days']))
    except rewards.FeedbackNotFound:
        abort(404)
    except rewards.AlreadyHandled as e:
        return _already_handled(e.status)
    except (psycopg.errors.UniqueViolation, psycopg.errors.SerializationFailure):
        return _already_handled('unknown')
    return out


@apost('/admin/system/feedback/<int:fid>/not-a-fault')
def post_admin_feedback_not_a_fault(s: t.SessionInfo, fid: int):
    require_admin(s)
    try:
        with api_tx('read committed') as tx:
            out = rewards.mark_not_a_fault(tx, fid, handled_by=s.email)
            record_audit(tx, s, 'feedback_not_a_fault', metadata=dict(feedback_id=fid))
    except rewards.FeedbackNotFound:
        abort(404)
    except rewards.AlreadyHandled as e:
        return _already_handled(e.status)
    except psycopg.errors.SerializationFailure:
        return _already_handled('unknown')
    return out
