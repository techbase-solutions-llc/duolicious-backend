"""Admin > Events (TEC-1845). Admin sessions only; every change is audited
in the transaction that makes it. These work whichever way the gathering
switches are set, so the owner can prepare before launch. Counts only:
nothing here names a guest or carries a guest's address."""
from __future__ import annotations

import duotypes as t
from database import api_tx
from service.admin import record_audit, require_admin
from service.api.decorators import aget, apatch, apost, validate
from service.events import EventError
from service.events import admin as ea


def _refused(e: EventError):
    return dict(error=e.reason), e.status


def _change(s: t.SessionInfo, action: str, metadata: dict, fn, status: int = 200):
    """Runs fn(tx) and audits it in the same transaction. Answers fn's own
    answer, or {ok: true}."""
    try:
        with api_tx() as tx:
            out = fn(tx)
            record_audit(tx, s, action, metadata=metadata)
    except EventError as e:
        return _refused(e)
    return (out if out is not None else dict(ok=True)), status


@aget('/admin/events')
def get_admin_events(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return ea.overview(tx), 200, {'Cache-Control': 'no-store'}


@aget('/admin/events/<slug>/weeks')
def get_admin_event_weeks(s: t.SessionInfo, slug: str):
    require_admin(s)
    try:
        with api_tx('read committed') as tx:
            return dict(weeks=ea.event_weeks(tx, slug))
    except EventError as e:
        return _refused(e)


@apost('/admin/events/organisers')
@validate(t.PostAdminOrganiser)
def post_admin_event_organiser(req: t.PostAdminOrganiser, s: t.SessionInfo):
    require_admin(s)

    def go(tx):
        return dict(id=ea.create_organiser(tx, s.person_id, name=req.name, email=req.email, kind=req.kind)['id'])
    return _change(s, 'events.organiser.create', dict(name=req.name, kind=req.kind), go, 201)


@apost('/admin/events/organisers/<int:oid>/approve')
@validate(t.PostAdminApproveOrganiser)
def post_admin_event_organiser_approve(req: t.PostAdminApproveOrganiser, s: t.SessionInfo, oid: int):
    require_admin(s)
    return _change(s, 'events.organiser.approve', dict(organiser_id=str(oid), kind=req.kind),
                   lambda tx: ea.approve_organiser(tx, s.person_id, oid, req.kind))


@apost('/admin/events/organisers/<int:oid>/decline')
@validate(t.PostAdminDeclineOrganiser)
def post_admin_event_organiser_decline(req: t.PostAdminDeclineOrganiser, s: t.SessionInfo, oid: int):
    """Refusing a request to host, with the reason the organiser is emailed
    (8.7). Audited with the reason as given."""
    require_admin(s)
    reason = ea.clean_reason(req.reason)
    return _change(s, 'events.organiser.decline', dict(organiser_id=str(oid), reason=reason),
                   lambda tx: ea.decline_organiser(tx, s.person_id, oid, reason=reason))


@apost('/admin/events/organisers/<int:oid>/revoke')
def post_admin_event_organiser_revoke(s: t.SessionInfo, oid: int):
    require_admin(s)
    return _change(s, 'events.organiser.revoke', dict(organiser_id=str(oid)),
                   lambda tx: ea.revoke_organiser(tx, s.person_id, oid))


@apost('/admin/events/<slug>/approve')
def post_admin_event_approve(s: t.SessionInfo, slug: str):
    require_admin(s)
    return _change(s, 'events.event.approve', dict(slug=slug), lambda tx: ea.approve_event(tx, s.person_id, slug))


@apost('/admin/events/<slug>/decline')
def post_admin_event_decline(s: t.SessionInfo, slug: str):
    require_admin(s)
    return _change(s, 'events.event.decline', dict(slug=slug), lambda tx: ea.decline_event(tx, s.person_id, slug))


@apost('/admin/events/<slug>/pause')
def post_admin_event_pause(s: t.SessionInfo, slug: str):
    require_admin(s)
    return _change(s, 'events.event.pause', dict(slug=slug), lambda tx: ea.pause_event(tx, s.person_id, slug))


@apost('/admin/events/<slug>/resume')
def post_admin_event_resume(s: t.SessionInfo, slug: str):
    require_admin(s)
    return _change(s, 'events.event.resume', dict(slug=slug), lambda tx: ea.resume_event(tx, s.person_id, slug))


@apost('/admin/events/<slug>/attending')
@validate(t.PostAhavahAttending)
def post_admin_event_attending(req: t.PostAhavahAttending, s: t.SessionInfo, slug: str):
    require_admin(s)
    return _change(s, 'events.event.attending', dict(slug=slug, on=req.on),
                   lambda tx: ea.set_attending(tx, s.person_id, slug, req.on))


@apatch('/admin/events/requests/<int:rid>')
@validate(t.PatchInviteRequest)
def patch_admin_event_request(req: t.PatchInviteRequest, s: t.SessionInfo, rid: int):
    require_admin(s)
    return _change(s, 'events.request.update', dict(request_id=str(rid), status=req.status),
                   lambda tx: ea.set_request(tx, s.person_id, rid, status=req.status, notes=req.notes))
