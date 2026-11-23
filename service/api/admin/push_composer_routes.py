"""The push composer's routes and the automatic pushes' rows (TEC-2182;
plan docs/plans/2026-11-19-push-composer.md, "API contract for the admin
card"). Admin only. Counts only: no route returns a member's name or
address, and no audit row carries one.

While AHAVAH_PUSH_COMPOSER_ENABLED is off, the send, cancel, list and
read routes answer 404. The config, drafts, audience count, dry run and
test send still answer, so the owner can try the composer out.
"""
from __future__ import annotations

import duotypes as t
from flask import abort, request

from database import api_tx
from service.admin import record_audit, require_admin, require_uuid
from service.api.decorators import aget, apatch, apost
from service.notifications import auto_pushes, composer
from service.notifications.composer import Refused


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400)
    return body


def _on() -> None:
    if not composer.switch_on():
        abort(404)


def _draft_id(body: dict) -> str:
    sid = body.get('draft_id')
    if not isinstance(sid, str):
        abort(400)
    return require_uuid(sid)


@aget('/admin/growth/push/composer')
def get_admin_push_composer(s: t.SessionInfo):
    """The switch, the tap targets, the limits and the filters' values."""
    require_admin(s)
    return composer.config()


@apost('/admin/growth/push/drafts')
def post_admin_push_draft(s: t.SessionInfo):
    require_admin(s)
    try:
        fields = composer.clean_draft(_body())
    except Refused as e:
        return e.answer()
    with api_tx() as tx:
        row = composer.create_draft(tx, fields, s.person_uuid)
        record_audit(tx, s, 'push_composer_draft', metadata=composer.audit_meta(row, change='create'))
        return composer.public(tx, row), 201


@apatch('/admin/growth/push/<send_id>')
def patch_admin_push_draft(s: t.SessionInfo, send_id: str):
    """Change an open draft. Any change clears its test."""
    require_admin(s)
    require_uuid(send_id)
    try:
        fields = composer.clean_draft(_body())
    except Refused as e:
        return e.answer()
    with api_tx() as tx:
        try:
            row = composer.update_draft(tx, send_id, fields)
        except Refused as e:
            return e.answer()
        record_audit(tx, s, 'push_composer_draft', metadata=composer.audit_meta(row, change='edit'))
        return composer.public(tx, row)


@apost('/admin/growth/push/audience')
def post_admin_push_audience(s: t.SessionInfo):
    """{filters, testers_only} -> {count, held_now: {quiet, resting},
    by_country, max_audience, over_cap}. Counts only. Changes nothing."""
    require_admin(s)
    body = _body()
    try:
        filters = composer.clean_filters(body.get('filters'))
        testers_only = body.get('testers_only', False)
        if not isinstance(testers_only, bool):
            raise Refused('invalid_testers_only', 400)
        if testers_only and filters:
            raise Refused('testers_only_with_filters', 400)
    except Refused as e:
        return e.answer()
    with api_tx('read committed') as tx:
        return composer.audience_summary(tx, filters, testers_only)


@apost('/admin/growth/push/test')
def post_admin_push_test(s: t.SessionInfo):
    """{draft_id}: the draft to the signed-in admin's own devices."""
    require_admin(s)
    sid = _draft_id(_body())
    try:
        res = composer.test_send(sid, s.person_id)
    except Refused as e:
        return e.answer()
    with api_tx() as tx:
        row = composer.get(tx, sid)
        record_audit(tx, s, 'push_composer_test',
                     metadata=composer.audit_meta(row, delivered=res['delivered'], reason=res['reason']))
    return res


@apost('/admin/growth/push/dry-run')
def post_admin_push_dry_run(s: t.SessionInfo):
    """{draft_id} or the draft's fields: what a send would do now. Writes
    nothing."""
    require_admin(s)
    body = _body()
    try:
        if body.get('draft_id') is not None:
            return composer.dry_run(send_id=_draft_id(body))
        return composer.dry_run(fields=composer.clean_draft(body))
    except Refused as e:
        return e.answer()


@apost('/admin/growth/push/send')
def post_admin_push_send(s: t.SessionInfo):
    """{draft_id, when: 'now' | ISO time, mode: 'barbados' | 'member_local'}.
    Freezes the tested draft into a send. A repeat returns the first."""
    require_admin(s)
    _on()
    body = _body()
    sid = _draft_id(body)
    # Read committed: the day count is read after the advisory lock, and
    # must see a send another request committed while this one waited.
    with api_tx('read committed') as tx:
        try:
            row, repeat = composer.send(tx, sid, body.get('when'), body.get('mode'))
        except Refused as e:
            return e.answer()
        if not repeat:
            now = body.get('when') == 'now'
            record_audit(tx, s, 'push_composer_send' if now else 'push_composer_schedule',
                         metadata=composer.audit_meta(row, when=body.get('when'), mode=row['mode']))
        out = composer.public(tx, row)
    if not repeat and body.get('when') == 'now':
        composer.run_soon(sid)
    return dict(out, repeat=repeat)


@apost('/admin/growth/push/<send_id>/cancel')
def post_admin_push_cancel(s: t.SessionInfo, send_id: str):
    require_admin(s)
    _on()
    require_uuid(send_id)
    with api_tx() as tx:
        try:
            row = composer.cancel(tx, send_id)
        except Refused as e:
            return e.answer()
        record_audit(tx, s, 'push_composer_cancel',
                     metadata=composer.audit_meta(row, sent=row['sent'], released=row['released']))
        return composer.public(tx, row)


@aget('/admin/growth/push/sends')
def get_admin_push_sends(s: t.SessionInfo):
    require_admin(s)
    _on()
    with api_tx('read committed') as tx:
        return dict(sends=composer.list_sends(tx))


@aget('/admin/growth/push/auto')
def get_admin_push_auto(s: t.SessionInfo):
    """The automatic pushes' rows: on or off, sent and tapped in 7 days."""
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(rows=auto_pushes.growth_rows(tx))


@apost('/admin/growth/push/auto/<name>/dry-run')
def post_admin_push_auto_dry_run(s: t.SessionInfo, name: str):
    """What the next tick would send. Writes nothing; works while off."""
    require_admin(s)
    if name not in auto_pushes.NAMES:
        abort(404)
    return auto_pushes.dry_run(name)


@apost('/admin/growth/push/auto/<name>/test')
def post_admin_push_auto_test(s: t.SessionInfo, name: str):
    """The sample to the signed-in admin's own devices; works while off."""
    require_admin(s)
    if name not in auto_pushes.NAMES:
        abort(404)
    why = auto_pushes.test_send(name, s.person_id)
    with api_tx() as tx:
        record_audit(tx, s, 'push_auto_test', metadata=dict(name=name, delivered=why is None, reason=why))
    return dict(delivered=why is None, reason=why, name=name)


@aget('/admin/growth/push/<send_id>')
def get_admin_push_send(s: t.SessionInfo, send_id: str):
    require_admin(s)
    _on()
    require_uuid(send_id)
    with api_tx('read committed') as tx:
        row = composer.get(tx, send_id)
        if row is None:
            abort(404)
        return composer.public(tx, row)
