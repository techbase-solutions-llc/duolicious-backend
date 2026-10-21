"""Notes held for Moderation > Text (TEC-1845, admin 4.1).

A recommendation's or an introduction's note caught by the rude words,
scam or contact details filter waits here (recommend.note_flag). The queue
shows the note, why it was held and who wrote it, never a recipient's
address or the two members' names. Approving sends it as if it had not been
held (an introduction opens with a fresh 14 days); rejecting sends nothing
and tells nobody.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from service.matchmaker import MatchmakerError, first_name

Kind = Literal['recommendation', 'introduction']
KINDS = ('recommendation', 'introduction')


def held_notes(tx) -> list[dict]:
    recs = tx.execute(
        """SELECT id, note, flag_reason, sender_first_name, sender_person_id, created_at
             FROM recommendation WHERE status = 'held' ORDER BY created_at""").fetchall()
    intros = tx.execute(
        """SELECT i.id, i.note, i.flag_reason, p.name, i.introducer_person_id, i.created_at
             FROM introduction i JOIN person p ON p.id = i.introducer_person_id
            WHERE i.status = 'held' ORDER BY i.created_at""").fetchall()
    out = [dict(kind='recommendation', id=r['id'], note=r['note'], flag_reason=r['flag_reason'],
                author_first_name=r['sender_first_name'] or 'Someone', author_person_id=r['sender_person_id'],
                created_at=r['created_at'].isoformat()) for r in recs]
    out += [dict(kind='introduction', id=r['id'], note=r['note'], flag_reason=r['flag_reason'],
                 author_first_name=first_name(r['name']), author_person_id=r['introducer_person_id'],
                 created_at=r['created_at'].isoformat()) for r in intros]
    return sorted(out, key=lambda x: x['created_at'])


def _held(tx, kind: str, id_: int) -> dict:
    if kind not in KINDS:
        raise MatchmakerError('not_found', 404)
    table = 'recommendation' if kind == 'recommendation' else 'introduction'
    row = tx.execute(f"SELECT * FROM {table} WHERE id = %(i)s AND status = 'held' FOR UPDATE",
                     dict(i=id_)).fetchone()
    if row is None:
        raise MatchmakerError('not_found', 404)
    return dict(row)


def approve(tx, admin_id: int, kind: str, id_: int, now: Optional[datetime] = None) -> dict:
    from service.matchmaker import introductions, recommend
    now = now or datetime.now(timezone.utc)
    _held(tx, kind, id_)
    if kind == 'recommendation':
        tx.execute("""UPDATE recommendation SET status = 'queued', reviewed_by = %(a)s, reviewed_at = %(now)s
                       WHERE id = %(i)s""", dict(a=admin_id, now=now, i=id_))
        recommend.send_recommendation(tx, id_)
    else:
        tx.execute("""UPDATE introduction SET status = 'open', opened_at = %(now)s, closes_at = %(closes)s,
                             reviewed_by = %(a)s, reviewed_at = %(now)s
                       WHERE id = %(i)s""",
                   dict(a=admin_id, now=now, closes=now + introductions.OPEN_FOR, i=id_))
        introductions.notify_both(tx, id_)
    return dict(ok=True)


def reject(tx, admin_id: int, kind: str, id_: int, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    _held(tx, kind, id_)
    table = 'recommendation' if kind == 'recommendation' else 'introduction'
    tx.execute(f"""UPDATE {table} SET status = 'rejected', reviewed_by = %(a)s, reviewed_at = %(now)s
                    WHERE id = %(i)s""", dict(a=admin_id, now=now, i=id_))
    return dict(ok=True)
