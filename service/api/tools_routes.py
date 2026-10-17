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
