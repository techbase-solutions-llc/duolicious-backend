"""Acting on the community (TEC-1897): who is waiting on a reply, unfinished
sign-ups and the weekly funnel. Admin role only; counts per member, never
content, never who liked whom.

Write to them (TEC-2210): POST /admin/community/waiting/<uuid>/note sends
the owner's note to one member on the list (service/admin/waiting_note.py).
  200 {sent, note_sent_at, can_note_at}
  400 {error: bad_note, detail}
  404 no such member
  409 {error: not_waiting | too_soon (with can_note_at) | rest_day
       | unsubscribed | not_reachable}
  502 {error: send_failed}, and nothing recorded
"""
from __future__ import annotations

import duotypes as t
from flask import abort

from database import api_tx
from service.admin import require_admin, require_uuid
from service.admin import waiting_note
from service.admin.jsonrow import iso_row
from service.admin.queries import community
from service.api.decorators import aget, apost, validate
from service.growth.queries import _excluded


@aget('/admin/community/waiting')
def get_admin_community_waiting(s: t.SessionInfo):
    require_admin(s)
    params = dict(ex=_excluded())
    with api_tx('read committed') as tx:
        summary = tx.execute(community.Q_WAITING_SUMMARY, params).fetchone()
        members = tx.execute(community.Q_WAITING_MEMBERS, params).fetchall()
    return dict(summary=iso_row(summary), members=[iso_row(r) for r in members])


@apost('/admin/community/waiting/<person_uuid>/note')
@validate(t.PostWaitingNote)
def post_admin_community_waiting_note(req: t.PostWaitingNote, s: t.SessionInfo, person_uuid: str):
    """Write to them: one note, by email, to one member someone is waiting
    on. One note to a member in 7 days."""
    require_admin(s)
    require_uuid(person_uuid)
    try:
        note = waiting_note.clean_note(req.note)
    except waiting_note.BadNote as e:
        return dict(error='bad_note', detail=str(e)), 400
    try:
        return waiting_note.send_note(s, person_uuid, note)
    except waiting_note.NotFound:
        abort(404)
    except waiting_note.Refused as e:
        return e.body(), 409
    except waiting_note.SendFailed:
        return dict(error='send_failed'), 502


@aget('/admin/community/unfinished')
def get_admin_community_unfinished(s: t.SessionInfo):
    """People who started sign-up and stopped (frames U.1 to U.4), each with
    the reminder's state and send date (TEC-2107,
    emails.unfinished_signup.reminder_states), and whether the reminder is
    on. The address is read to look the reminder up and never returned."""
    require_admin(s)
    from emails.unfinished_signup import reminder_states
    from service.admin.queries.signups import Q_UNFINISHED
    from service.campaigns.switches import enabled
    with api_tx('read committed') as tx:
        found = [dict(r) for r in tx.execute(Q_UNFINISHED, dict(ex=_excluded())).fetchall()]
        states = reminder_states(tx, found)
    rows = []
    for r, (state, reminded_at) in zip(found, states):
        rows.append(iso_row(dict(started_at=r['started_at'], last_saved_at=r['last_saved_at'],
                                 furthest_step=r['furthest_step'], reminder_state=state,
                                 reminded_at=reminded_at)))
    return dict(count=len(rows), rows=rows, reminder_on=enabled('unfinished_signup_reminder'))


@aget('/admin/community/funnel')
def get_admin_community_funnel(s: t.SessionInfo):
    """Likes, matches, first messages and replies per Barbados week, 12
    weeks, oldest first (frame O.1)."""
    require_admin(s)
    with api_tx('read committed') as tx:
        weeks = [iso_row(r) for r in tx.execute(community.Q_WEEKLY_FUNNEL,
                                                dict(ex=_excluded())).fetchall()]
    return dict(weeks=weeks)
