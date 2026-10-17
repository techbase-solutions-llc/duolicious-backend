"""Together, the public routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as questions_routes is.
Playing needs no account: a player proves who they are with the
X-Tool-Token header the device keeps. Saving uses the onboardee or member
session /check-otp already issues. Every route but /tools/status answers
404 while together_live is off.
"""
from __future__ import annotations

from typing import Optional

from flask import request

import duotypes as t
from database import api_tx
from service.api.decorators import adelete, aget, apost, get, limiter, post, validate


@get('/tools/status')
def get_tools_status():
    """What the web needs before it shows Together: whether it is live, and
    whether the invite email may be offered."""
    from service.tools import live, switch_on
    return (dict(live=live(), invite_email=switch_on('together_invite_email')),
            200, {'Cache-Control': 'no-store'})


_start_limit = limiter.shared_limit('30 per hour', scope='tools_start')
_answer_limit = limiter.shared_limit('600 per hour', scope='tools_answer')


def _token() -> Optional[str]:
    return request.headers.get('X-Tool-Token') or None


def _off():
    return dict(error='not_found'), 404


def _refused(e):
    return dict(error=e.reason), e.status


@apost('/tools/sessions', auth='optional', expected_onboarding_status=None,
       limiter=_start_limit)
@validate(t.PostToolSession)
def post_tool_session(req: t.PostToolSession, s: Optional[t.SessionInfo]):
    """Start a game or a checklist. No account needed; a signed-in
    member's session is theirs from the start."""
    from service.person.attribution import clean_first_touch
    from service.tools import live, sessions
    if not live():
        return _off()
    member = s if s is not None and s.person_id is not None else None
    try:
        with api_tx() as tx:
            out = sessions.start(tx, kind=req.kind, mode=req.mode, member=member,
                                 utm=clean_first_touch(req.first_touch))
    except sessions.ToolError as e:
        return _refused(e)
    return out, 201


@apost('/tools/sessions/<sid>/answers', auth='optional', expected_onboarding_status=None,
       limiter=_answer_limit)
@validate(t.PostToolAnswers)
def post_tool_answers(req: t.PostToolAnswers, s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            saved = sessions.save_answers(tx, player, [a.model_dump() for a in req.answers],
                                          role=req.role)
    except sessions.ToolError as e:
        return _refused(e)
    return dict(saved=saved)


@apost('/tools/sessions/<sid>/finish', auth='optional', expected_onboarding_status=None,
       limiter=_answer_limit)
def post_tool_finish(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        # Read committed: see sessions.finish.
        with api_tx('read committed') as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            out = sessions.finish(tx, player)
    except sessions.ToolError as e:
        return _refused(e)
    return out['view']


@aget('/tools/sessions/<sid>', auth='optional', expected_onboarding_status=None)
def get_tool_session(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.view(tx, player['session_id'], player['player_id'])
    except sessions.ToolError as e:
        return _refused(e)


_invite_read_limit = limiter.shared_limit('120 per hour', scope='tools_invite_read')
_join_limit = limiter.shared_limit('60 per hour', scope='tools_join')


@get('/tools/i/<invite>', limiter=_invite_read_limit)
def get_tool_invite(invite: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            return sessions.invite_info(tx, invite)
    except sessions.ToolError as e:
        return _refused(e)


@apost('/tools/i/<invite>/players', auth='optional', expected_onboarding_status=None,
       limiter=_join_limit)
@validate(t.PostToolJoin)
def post_tool_join(req: t.PostToolJoin, s: Optional[t.SessionInfo], invite: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            out = sessions.join(tx, invite, display=req.display, s=s)
    except sessions.ToolError as e:
        return _refused(e)
    return out, 201


def _board_change(s, sid: str, gid: int, removed: bool):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.set_removed(tx, player, gid, removed)
    except sessions.ToolError as e:
        return _refused(e)


@adelete('/tools/sessions/<sid>/players/<int:gid>', auth='optional',
         expected_onboarding_status=None)
def delete_tool_board_name(s: Optional[t.SessionInfo], sid: str, gid: int):
    return _board_change(s, sid, gid, True)


@apost('/tools/sessions/<sid>/players/<int:gid>/restore', auth='optional',
       expected_onboarding_status=None)
def post_tool_board_restore(s: Optional[t.SessionInfo], sid: str, gid: int):
    return _board_change(s, sid, gid, False)


@apost('/tools/sessions/<sid>/claim', expected_onboarding_status=None)
@validate(t.PostToolClaim)
def post_tool_claim(req: t.PostToolClaim, s: t.SessionInfo, sid: str):
    """Save a result with the signed-in session's address. The web gets
    that session from /request-otp and /check-otp (with the tool's
    source); a member is already signed in."""
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.claim(tx, player, s, req.display)
    except sessions.ToolError as e:
        return _refused(e)


_share_read_limit = limiter.shared_limit('300 per hour', scope='tools_share_read')
_share_open_limit = limiter.shared_limit('60 per hour', scope='tools_share_open')


@get('/tools/r/<share>', limiter=_share_read_limit)
def get_tool_public(share: str):
    """The public summary a shared link and its images read. No answers."""
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            return sessions.public_summary(tx, share), 200, {'Cache-Control': 'no-store'}
    except sessions.ToolError as e:
        return dict(error=e.reason), e.status, {'Cache-Control': 'no-store'}


@post('/tools/r/<share>/open', limiter=_share_open_limit)
def post_tool_share_open(share: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    with api_tx() as tx:
        sessions.count_open(tx, share)
    return '', 204


@adelete('/tools/sessions/<sid>', auth='optional', expected_onboarding_status=None)
def delete_tool_session(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            sessions.delete_session(tx, player)
    except sessions.ToolError as e:
        return _refused(e)
    return '', 204
