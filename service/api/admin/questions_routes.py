"""Admin > Questions (TEC-1845). Admin sessions only; every change is
audited in the transaction that makes it."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duotypes as t
from database import api_tx
from service.admin import record_audit, require_admin
from service.api.decorators import adelete, aget, apatch, apost, aput, validate
from service.questions import admin as qa


def _day(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@aget('/admin/questions')
def get_admin_questions(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(bank=qa.bank_rows(tx), switches=qa.switch_states())


@apatch('/admin/questions/<key>')
@validate(t.PatchAdminQuestion)
def patch_admin_question(req: t.PatchAdminQuestion, s: t.SessionInfo, key: str):
    require_admin(s)
    try:
        with api_tx() as tx:
            row = qa.update_question(tx, key, active=req.active, labels=req.labels)
            record_audit(tx, s, 'questions.update', metadata=dict(key=key, active=req.active, labels=req.labels))
            return row
    except qa.QuestionEditRefused as e:
        return dict(error=str(e)), (404 if str(e) == 'unknown_question' else 400)


@aget('/admin/questions/schedule')
def get_admin_question_schedule(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(weeks=qa.schedule_rows(tx))


@aput('/admin/questions/schedule/<live_on>')
@validate(t.PutQuestionDrop)
def put_admin_question_drop(req: t.PutQuestionDrop, s: t.SessionInfo, live_on: str):
    require_admin(s)
    day = _day(live_on)
    if day is None:
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            qa.set_drop(tx, day, req.prompt_key)
            record_audit(tx, s, 'questions.schedule', metadata=dict(live_on=live_on, prompt_key=req.prompt_key))
            return dict(weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@adelete('/admin/questions/schedule/<live_on>')
def delete_admin_question_drop(s: t.SessionInfo, live_on: str):
    require_admin(s)
    day = _day(live_on)
    if day is None:
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            qa.clear_drop(tx, day)
            record_audit(tx, s, 'questions.unschedule', metadata=dict(live_on=live_on))
            return dict(weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@apost('/admin/questions/schedule/approve')
@validate(t.PostApproveDrops)
def post_admin_question_approve(req: t.PostApproveDrops, s: t.SessionInfo):
    require_admin(s)
    days = [_day(v) for v in req.live_on]
    if any(d is None for d in days):
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            approved = qa.approve(tx, days)
            record_audit(tx, s, 'questions.approve', metadata=dict(live_on=approved))
            return dict(approved=approved, weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@aget('/admin/questions/pushes')
def get_admin_question_pushes(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(weeks=qa.push_rows(tx))
