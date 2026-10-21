"""Moderation tab — photos + rude-messages routes.

Reports sub-tab is the EXISTING /admin/reports (service/api/moderation_routes.py),
which the FE will call directly — we don't duplicate it here."""
from __future__ import annotations

import duotypes as t
from flask import request, abort

from service.api.decorators import aget, apost
from service.admin import require_admin, record_audit
from service.admin.queries import (
    Q_PHOTOS_LIST, Q_PHOTOS_KPIS, Q_RUDE_MESSAGES, Q_PHOTO_GATE_KPIS,
)
from service.photo_gate import photo_gate_enabled
from emails.photo_removed import send_photo_removed
from database import api_tx


@aget('/admin/moderation/photos')
def get_moderation_photos(s: t.SessionInfo):
    require_admin(s)
    state = (request.args.get('state') or 'pending').strip()
    with api_tx('read committed') as tx:
        rows = [dict(r) for r in tx.execute(Q_PHOTOS_LIST, dict(state=state)).fetchall()]
        kpis = tx.execute(Q_PHOTOS_KPIS).fetchone() or {}
        gate = dict(tx.execute(Q_PHOTO_GATE_KPIS).fetchone() or {})
    # The photo gate (findings 91, 99): whether it is on, and how many
    # members it holds or would hold.
    gate['enabled'] = photo_gate_enabled()
    return {'rows': rows, 'kpis': dict(kpis), 'photo_gate': gate}


@apost('/admin/moderation/photos/<photo_uuid>/approve')
def approve_photo_admin(s: t.SessionInfo, photo_uuid: str):
    require_admin(s)
    with api_tx() as tx:
        row = tx.execute(
            """
            UPDATE photo
               SET moderation_status = 'approved', moderated_at = NOW(),
                   -- A person looked at a photo the detector saw no face
                   -- in and accepted it (finding 97). Kept on the photo so
                   -- the face rule never holds it again and the photo gate
                   -- counts it as showing the member.
                   face_confirmed_at = CASE
                       WHEN face_count = 0 THEN COALESCE(face_confirmed_at, NOW())
                       ELSE face_confirmed_at
                   END
             WHERE uuid = %(uuid)s
            RETURNING person_id, face_confirmed_at IS NOT NULL AS face_confirmed
            """,
            dict(uuid=photo_uuid),
        ).fetchone()
        if row is None:
            abort(404)
        record_audit(
            tx, s, 'approve_photo',
            target_email=None, target_uuid=None,
            metadata={'photo_uuid': photo_uuid,
                      'face_confirmed': bool(row['face_confirmed'])},
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
        # Only the flagged word or phrase leaves the server, never the rest
        # of the message (owner, 13 Oct 2026).
        from antiabuse.antirude.chat import rude_matches
        for r in rows:
            r['snippet'] = ', '.join(rude_matches(r['snippet'] or '')) or '(flagged)'
        return {'rows': rows}
    except Exception:
        # Table may not exist on a given env; degrade gracefully so the
        # FE shows the "no data" state instead of 500.
        return {'rows': [], 'note': 'rude_message query failed | see backend logs'}


# The messages between a reporter and the person they reported, for the
# dashboard's "Show messages" (TEC-1845, better reports; brief
# 2026-10-20-admin-report-messages.md). The report email no longer carries
# them. Staff only, only for a pair with a report on file, and every opening
# is audited, because it reads members' private messages.
_Q_REPORT_PAIR = """
SELECT reporter.uuid::TEXT AS reporter_uuid, reporter.name AS reporter_name,
       reported.uuid::TEXT AS reported_uuid, reported.name AS reported_name
  FROM person_report r
  JOIN person reporter ON reporter.id = r.reporter_id
  JOIN person reported ON reported.id = r.reported_id
 WHERE reporter.uuid = %(reporter)s::uuid
   AND reported.uuid = %(reported)s::uuid
 LIMIT 1
"""


def _uuid_arg(name: str) -> str:
    import uuid as _uuid
    try:
        return str(_uuid.UUID(request.args.get(name) or ''))
    except ValueError:
        abort(400)


@aget('/admin/reports/messages')
def get_report_messages(s: t.SessionInfo):
    require_admin(s)
    reporter, reported = _uuid_arg('reporter'), _uuid_arg('reported')

    from datetime import datetime, timezone

    from antiabuse.lodgereport import first_name, message_text
    from antiabuse.sql import Q_LAST_MESSAGES

    with api_tx() as tx:
        pair = tx.execute(_Q_REPORT_PAIR, dict(reporter=reporter, reported=reported)).fetchone()
        if pair is None:
            abort(404)
        rows = tx.execute(
            Q_LAST_MESSAGES, dict(subject_uuid=reporter, object_uuid=reported)).fetchall()
        record_audit(
            tx, s, 'view_report_messages',
            target_email=None, target_uuid=reported,
            metadata={'reporter_uuid': reporter, 'reported_uuid': reported,
                      'count': len(rows)},
        )

    names = {'reporter': first_name(pair['reporter_name']),
             'reported': first_name(pair['reported_name'])}
    messages = []
    for r in rows:
        who = 'reporter' if r['sent_by'] == 'reporter' else 'reported'
        sent_at = datetime.fromtimestamp((int(r['id']) >> 8) / 1_000_000, tz=timezone.utc)
        messages.append({
            'from': who,
            'first_name': names[who],
            'sent_at': sent_at.isoformat(),
            'text': message_text(r),
            'after_unmatch': bool(r['held']),
        })
    return {'count': len(messages), 'messages': messages}
