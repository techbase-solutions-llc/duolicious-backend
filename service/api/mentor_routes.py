"""Matchmaker, the mentor routes (TEC-1845, sections 6 to 8).

Imported at the bottom of service/api/__init__.py, after matchmaker_routes,
whose before_request hook answers 404 for every /mentor, /conversations/
<uuid>/share, /conversations/<uuid>/sharing and /matches/<uuid>/mentor-note
path while matchmaker_live is off.

The single's side (member session): GET /mentor, the invitation, removing
the mentor and sharing one conversation at a time. Each needs
matchmaker_mentors, except GET /conversations/<uuid>/sharing, which stays
open while live so the other person is still told if mentors are switched
off later.

The mentor's side (header X-Mentor-Token, Task 12) is below it.
"""
from __future__ import annotations

from flask import request

import duotypes as t
from service.api.decorators import (
    adelete,
    aget,
    apost,
    delete,
    get,
    limiter,
    put,
    shared_recipient_limit,
    validate,
)
from service.api.matchmaker_routes import _NO_STORE, _member_call, _off, _refused


# ---------------------------------------------------------------------------
# The single's side
# ---------------------------------------------------------------------------

@aget('/mentor')
def get_mentor(s: t.SessionInfo):
    from service.matchmaker import mentors
    return _member_call('matchmaker_mentors', lambda tx: mentors.state(tx, s.person_id))


_invite_ip_limit = limiter.shared_limit('10 per hour', scope='mm_mentor_invite')


@apost('/mentor/invite', limiter=[_invite_ip_limit, shared_recipient_limit])
@validate(t.PostMentorInvite)
def post_mentor_invite(req: t.PostMentorInvite, s: t.SessionInfo):
    """6.1's "Send invitation". A refused address (the free defences) is
    answered as invited, and nothing is written or sent."""
    from service import leads
    from service.matchmaker import mentors, surface_on
    if not surface_on('matchmaker_mentors'):
        return _off()
    cleaned = leads.clean_email(req.email)
    if cleaned is None:
        return dict(error='bad_email'), 400, _NO_STORE
    if req.relation not in mentors.RELATIONS:
        return dict(error='bad_relation'), 400, _NO_STORE
    # mail_refusal opens its own read, so it runs before the transaction.
    if leads.mail_refusal(email=cleaned[0], ip=request.remote_addr, stamp=req.signup_stamp,
                          website=req.website):
        return (dict(state='invited', email=cleaned[0], relation=req.relation, shared=[]),
                201, _NO_STORE)
    return _member_call('matchmaker_mentors', lambda tx: mentors.invite(
        tx, s.person_id, cleaned[0], req.relation), status=201, isolation='read committed')


@adelete('/mentor/invite')
def delete_mentor_invite(s: t.SessionInfo):
    from service.matchmaker import mentors
    return _member_call('matchmaker_mentors', lambda tx: mentors.cancel_invite(tx, s.person_id))


@adelete('/mentor')
def delete_mentor(s: t.SessionInfo):
    from service.matchmaker import mentors
    return _member_call('matchmaker_mentors', lambda tx: mentors.remove(tx, s.person_id))


@apost('/conversations/<uuid>/share')
def post_conversation_share(s: t.SessionInfo, uuid: str):
    from service.matchmaker import mentors
    return _member_call('matchmaker_mentors', lambda tx: mentors.share(tx, s.person_id, uuid),
                        isolation='read committed')


@adelete('/conversations/<uuid>/share')
def delete_conversation_share(s: t.SessionInfo, uuid: str):
    from service.matchmaker import mentors
    return _member_call('matchmaker_mentors', lambda tx: mentors.unshare(tx, s.person_id, uuid))


@aget('/conversations/<uuid>/sharing')
def get_conversation_sharing(s: t.SessionInfo, uuid: str):
    """Both people's notice and lines (8.1 to 8.4). Open while live,
    whichever way matchmaker_mentors is set."""
    from database import api_tx
    from service.matchmaker import live, mentors
    if not live():
        return _off()
    with api_tx('read committed') as tx:
        out = mentors.sharing(tx, s.person_id, uuid)
    return out, 200, _NO_STORE


# ---------------------------------------------------------------------------
# The mentor's side (section 7). Header X-Mentor-Token, except the sign-in
# routes. 404 until matchmaker_mentors; every answer is no-store.
# ---------------------------------------------------------------------------

def _mentor_token():
    return request.headers.get('X-Mentor-Token') or None


def _mentor_call(fn, *, status: int = 200, isolation: str = 'read committed'):
    """Runs fn(tx, mentor) for the token's mentor."""
    from database import api_tx
    from service.matchmaker import MatchmakerError, mentor_view, surface_on
    if not surface_on('matchmaker_mentors'):
        return _off()
    try:
        with api_tx(isolation) as tx:
            out = fn(tx, mentor_view.mentor_for(tx, _mentor_token()))
    except MatchmakerError as e:
        return _refused(e)
    return out, status, _NO_STORE


@get('/mentor/invites/<token>')
def get_mentor_invite(token: str):
    """The sign-in page's look at its invitation (7.1)."""
    from database import api_tx
    from service.matchmaker import MatchmakerError, mentor_view, surface_on
    if not surface_on('matchmaker_mentors'):
        return _off()
    try:
        with api_tx('read committed') as tx:
            out = mentor_view.invitation(tx, token)
    except MatchmakerError as e:
        return _refused(e)
    return out, 200, _NO_STORE


@apost('/mentor/session', auth='optional', expected_onboarding_status=None)
@validate(t.PostMentorSession)
def post_mentor_session(req: t.PostMentorSession, s):
    """With an invitation token, the link signs the mentor in once. Without
    one it needs the session /check-otp leaves for the mentor's address."""
    from database import api_tx
    from service.matchmaker import MatchmakerError, mentor_view, surface_on
    if not surface_on('matchmaker_mentors'):
        return _off()
    if not req.invite_token and (s is None or not s.signed_in):
        return dict(error='signed_out'), 401, _NO_STORE
    try:
        with api_tx('read committed') as tx:
            out = mentor_view.start_session(tx, invite_token=req.invite_token,
                                            session_email=None if req.invite_token else s.email)
    except MatchmakerError as e:
        return _refused(e)
    return out, 201, _NO_STORE


@delete('/mentor/session')
def delete_mentor_session():
    from database import api_tx
    from service.matchmaker import mentor_view, surface_on
    if not surface_on('matchmaker_mentors'):
        return _off()
    with api_tx() as tx:
        mentor_view.end_session(tx, _mentor_token())
    return {}, 200, _NO_STORE


@get('/mentor/me')
def get_mentor_me():
    from service.matchmaker import mentor_view
    return _mentor_call(lambda tx, m: mentor_view.singles(tx, m))


@get('/mentor/singles/<single>/matches')
def get_mentor_matches(single: str):
    from service.matchmaker import mentor_view
    return _mentor_call(lambda tx, m: dict(matches=mentor_view.matches(tx, m, single)))


@get('/mentor/singles/<single>/matches/<match>')
def get_mentor_match(single: str, match: str):
    from service.matchmaker import mentor_view
    return _mentor_call(lambda tx, m: mentor_view.match_detail(tx, m, single, match))


@get('/mentor/singles/<single>/matches/<match>/conversation')
def get_mentor_conversation(single: str, match: str):
    from service.matchmaker import mentor_view
    raw = request.args.get('before')
    before = int(raw) if raw and raw.isdigit() else None
    return _mentor_call(lambda tx, m: mentor_view.conversation(tx, m, single, match, before))


@put('/mentor/singles/<single>/notes/<match>')
@validate(t.PutMentorNote)
def put_mentor_note(req: t.PutMentorNote, single: str, match: str):
    from service.matchmaker import mentor_view

    def go(tx, m):
        mentor_view.save_note(tx, m, single, match, req.note)
        return dict(saved=True)
    return _mentor_call(go, isolation='REPEATABLE READ')


@aget('/matches/<uuid>/mentor-note')
def get_match_mentor_note(s: t.SessionInfo, uuid: str):
    """8.5: the single reads their mentor's note on that match."""
    from service.matchmaker import MatchmakerError, mentor_view

    def go(tx):
        note = mentor_view.note_for_single(tx, s.person_id, uuid)
        if note is None:
            raise MatchmakerError('not_found', 404)
        return dict(note=note)
    return _member_call('matchmaker_mentors', go, isolation='read committed')
