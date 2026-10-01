"""Moderation tab — photos + rude-messages routes.

Reports sub-tab is the EXISTING /admin/reports (service/api/moderation_routes.py),
which the FE will call directly — we don't duplicate it here."""
from __future__ import annotations

import duotypes as t
from flask import request, abort

from service.api.decorators import aget, apost
from service.admin import require_admin, record_audit
from service.admin.queries import Q_PHOTOS_LIST, Q_PHOTOS_KPIS, Q_RUDE_MESSAGES
from emails.photo_removed import send_photo_removed
from database import api_tx


@aget('/admin/moderation/photos')
def get_moderation_photos(s: t.SessionInfo):
    require_admin(s)
    state = (request.args.get('state') or 'pending').strip()
    with api_tx('read committed') as tx:
        rows = [dict(r) for r in tx.execute(Q_PHOTOS_LIST, dict(state=state)).fetchall()]
        kpis = tx.execute(Q_PHOTOS_KPIS).fetchone() or {}
    return {'rows': rows, 'kpis': dict(kpis)}


@apost('/admin/moderation/photos/<photo_uuid>/approve')
def approve_photo_admin(s: t.SessionInfo, photo_uuid: str):
    require_admin(s)
    with api_tx() as tx:
        row = tx.execute(
            """
            UPDATE photo
               SET moderation_status = 'approved', moderated_at = NOW()
             WHERE uuid = %(uuid)s
            RETURNING person_id
            """,
            dict(uuid=photo_uuid),
        ).fetchone()
        if row is None:
            abort(404)
        record_audit(
            tx, s, 'approve_photo',
            target_email=None, target_uuid=None,
            metadata={'photo_uuid': photo_uuid},
        )
    return {'ok': True}


@apost('/admin/moderation/photos/<photo_uuid>/reject')
def reject_photo_admin(s: t.SessionInfo, photo_uuid: str):
    """Take a photo down, and tell the member.

    This used to set the status and say nothing: the photo simply stopped
    appearing and the member was left to wonder. Body `{notify}` defaults to
    true. The note goes out AFTER the takedown has committed and can never
    undo it: a mail failure is caught and reported back as `notified: false`
    so the operator knows whether the member was told.
    """
    require_admin(s)
    notify = (request.get_json(silent=True) or {}).get('notify', True) is not False
    with api_tx() as tx:
        row = tx.execute(
            """
            UPDATE photo
               SET moderation_status = 'rejected', moderated_at = NOW()
             WHERE uuid = %(uuid)s
            RETURNING person_id
            """,
            dict(uuid=photo_uuid),
        ).fetchone()
        if row is None:
            abort(404)
        owner = tx.execute("SELECT email, name FROM person WHERE id = %(i)s",
                           dict(i=row['person_id'])).fetchone()
        record_audit(
            tx, s, 'reject_photo',
            target_email=None, target_uuid=None,
            metadata={'photo_uuid': photo_uuid, 'notify': notify},
        )
    notified = False
    if notify and owner:
        try:
            notified = bool(send_photo_removed(owner['email'], owner['name']))
        except Exception as e:
            print(f'reject_photo: note not sent ({type(e).__name__})')
    return {'ok': True, 'notified': notified}


@aget('/admin/moderation/rude-messages')
def get_moderation_rude_messages(s: t.SessionInfo):
    require_admin(s)
    try:
        with api_tx('read committed') as tx:
            rows = [dict(r) for r in tx.execute(Q_RUDE_MESSAGES).fetchall()]
        return {'rows': rows}
    except Exception:
        # Table may not exist on a given env; degrade gracefully so the
        # FE shows the "no data" state instead of 500.
        return {'rows': [], 'note': 'rude_message query failed | see backend logs'}
