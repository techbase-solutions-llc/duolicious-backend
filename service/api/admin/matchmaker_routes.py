"""Admin, the matchmaker (TEC-1845): Growth's tiles, a member's Connections
and Moderation > Text. Admin sessions only, whichever way the matchmaker
switches are set. Counts only, and never a recipient: the one exception is
a held note's own text in Moderation > Text. Every change is audited in the
transaction that makes it."""
from __future__ import annotations

import duotypes as t
from database import api_tx
from service.admin import record_audit, require_admin
from service.api.decorators import aget, apost
from service.matchmaker import MatchmakerError, is_uuid

_NO_STORE = {'Cache-Control': 'no-store'}


@aget('/admin/matchmaker')
def get_admin_matchmaker(s: t.SessionInfo):
    from service.matchmaker import admin
    require_admin(s)
    with api_tx('read committed') as tx:
        return admin.counts(tx), 200, _NO_STORE


@aget('/admin/users/<who>/connections')
def get_admin_user_connections(s: t.SessionInfo, who: str):
    """6.1, by person id or uuid."""
    from service.matchmaker import admin
    require_admin(s)
    with api_tx('read committed') as tx:
        if who.isdigit():
            row = tx.execute('SELECT id FROM person WHERE id = %(i)s', dict(i=int(who))).fetchone()
        elif is_uuid(who):
            row = tx.execute('SELECT id FROM person WHERE uuid = %(u)s::uuid', dict(u=who)).fetchone()
        else:
            row = None
        if row is None:
            return dict(error='not_found'), 404
        return admin.connections(tx, row['id']), 200, _NO_STORE


@aget('/admin/moderation/text')
def get_admin_moderation_text(s: t.SessionInfo):
    from service.matchmaker import moderation
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(held=moderation.held_notes(tx)), 200, _NO_STORE


def _review(s: t.SessionInfo, verb: str, kind: str, id_: int):
    from service.matchmaker import moderation
    from service.matchmaker.mail import collect_pushes
    require_admin(s)
    try:
        with collect_pushes():
            with api_tx() as tx:
                out = getattr(moderation, verb)(tx, s.person_id, kind, id_)
                record_audit(tx, s, f'matchmaker.note.{verb}', metadata=dict(kind=kind, id=str(id_)))
    except MatchmakerError as e:
        return dict(error=e.reason), e.status
    return out, 200


@apost('/admin/moderation/text/<kind>/<int:id_>/approve')
def post_admin_moderation_text_approve(s: t.SessionInfo, kind: str, id_: int):
    return _review(s, 'approve', kind, id_)


@apost('/admin/moderation/text/<kind>/<int:id_>/reject')
def post_admin_moderation_text_reject(s: t.SessionInfo, kind: str, id_: int):
    return _review(s, 'reject', kind, id_)
