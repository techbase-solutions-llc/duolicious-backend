"""Your Ahavah, the light sign-in's routes (TEC-1845, in-app plan release 4).

Imported at the bottom of service/api/__init__.py. Every /your-ahavah
route answers 404 while light_sign_in (or matchmaker_live) is off, before
the body check, the limits or the token lookup run, so a dark release says
nothing about itself.

  POST   /your-ahavah/code     {email, website?, signup_stamp?}
                               -> 202 {request_token}, whatever happens
  POST   /your-ahavah/session  {request_token, code}
                               -> 200 {address_token, expires_at}
                               |  401 {error: 'wrong_code' | 'expired'}
  GET    /your-ahavah          X-Address-Token -> 200 what the address holds
  POST   /your-ahavah/start-profile  X-Address-Token, {source?, inviter_code?}
                               -> 200 {session_token, onboarded, ...}: what
                                  /request-otp and a right /check-otp give
                               |  401 {error: 'expired'} | 409 {error: 'member'}
                               |  403 {error: 'refused'}
  POST   /your-ahavah/delete   X-Address-Token -> 200 {deleted: true}
                               |  409 {error: 'member'}
  DELETE /your-ahavah/session  X-Address-Token -> 200 {} (signs out)

The address token goes in X-Address-Token only. The member routes read the
Authorization bearer from duo_session, where an address token never is, so
it opens none of them; and these routes never read a bearer.
"""
from __future__ import annotations

from flask import request

import duotypes as t
from database import api_tx
from service.api.decorators import (
    app,
    delete,
    get,
    limiter,
    post,
    shared_otp_limit,
    shared_recipient_limit,
    validate,
)

_NO_STORE = {'Cache-Control': 'no-store'}
_PREFIX = '/your-ahavah'


def _off():
    return dict(error='not_found'), 404


def _your_ahavah_dark():
    path = request.path.rstrip('/') or '/'
    if path == _PREFIX or path.startswith(_PREFIX + '/'):
        from service.your_ahavah import on
        if not on():
            return _off()
    return None


# First among the before_request functions, ahead of Flask-Limiter's, so a
# dark call is never counted or answered 429 (as the matchmaker's).
app.before_request_funcs.setdefault(None, []).insert(0, _your_ahavah_dark)


def _token():
    return request.headers.get('X-Address-Token') or None


def _refused(e):
    return dict(error=e.reason), e.status, _NO_STORE


_code_ip_limit = limiter.shared_limit('10 per hour; 30 per day', scope='your_ahavah_code')
_session_ip_limit = limiter.shared_limit('10 per minute; 40 per day', scope='your_ahavah_session')

_Q_BANNED = """
    SELECT 1 FROM banned_person
     WHERE (normalized_email = %(ne)s OR ip_address = %(ip)s) AND expires_at > NOW()
     LIMIT 1
"""


def _quietly_refused(req: t.PostYourAhavahCode) -> bool:
    """The free defences every unasked-for email has (service.leads.
    mail_refusal: the hidden field, the page stamp, the per-address and
    per-network limits, the bad-domain list), a banned address or network
    and a blocked network. A refusal is answered exactly as a send."""
    from service import leads
    from service.person import _ip_blocked
    if leads.mail_refusal(email=req.email, ip=request.remote_addr, stamp=req.signup_stamp,
                          website=req.website) is not None:
        return True
    if _ip_blocked(req.email):
        return True
    cleaned = leads.clean_email(req.email)
    if cleaned is None:
        return True
    with api_tx('read committed') as tx:
        return tx.execute(_Q_BANNED, dict(ne=cleaned[1], ip=request.remote_addr)).fetchone() is not None


@post('/your-ahavah/code', limiter=[_code_ip_limit, shared_otp_limit, shared_recipient_limit])
@validate(t.PostYourAhavahCode)
def post_your_ahavah_code(req: t.PostYourAhavahCode):
    """A sign-in code for the light sign-in. The answer is the same for an
    address that holds something, one that holds nothing, a member's, a
    refused one and a malformed one: only the inbox learns which."""
    from service import your_ahavah
    refused = _quietly_refused(req)
    with api_tx() as tx:
        handle, code = your_ahavah.request_code(tx, req.email, refused=refused)
    if code is not None:
        your_ahavah.send_code(req.email.strip().lower(), code)
    return dict(request_token=handle), 202, _NO_STORE


@post('/your-ahavah/session', limiter=_session_ip_limit)
@validate(t.PostYourAhavahSession)
def post_your_ahavah_session(req: t.PostYourAhavahSession):
    from service import your_ahavah
    try:
        with api_tx() as tx:
            out = your_ahavah.check_code(tx, req.request_token, req.code.strip())
    except your_ahavah.YourAhavahError as e:
        return _refused(e)
    if 'error' in out:
        # Answered after the commit, so the wrong code is counted.
        return out, 401, _NO_STORE
    return out, 200, _NO_STORE


@get('/your-ahavah')
def get_your_ahavah():
    from service import your_ahavah
    try:
        with api_tx() as tx:
            who = your_ahavah.address_for(tx, _token())
            out = your_ahavah.held(tx, who['normalized_email'])
    except your_ahavah.YourAhavahError as e:
        return _refused(e)
    from service.your_ahavah import _iso
    return dict(email=who['email'], expires_at=_iso(who['session_expires_at']), **out), 200, _NO_STORE


# As the code is entered (/your-ahavah/session): a session is the proof,
# and nothing is mailed.
_start_ip_limit = limiter.shared_limit('10 per minute; 40 per day', scope='your_ahavah_start')


@post('/your-ahavah/start-profile', limiter=_start_ip_limit)
@validate(t.PostYourAhavahStartProfile)
def post_your_ahavah_start_profile(req: t.PostYourAhavahStartProfile):
    """Start a matchmaking profile with the address just proved, with no
    second code (design 4.2). Answers what /request-otp and a right code at
    /check-otp give a new address, and ends the address session."""
    from service import your_ahavah
    from service.person import sign_up_closed_to
    try:
        with api_tx('read committed') as tx:
            who = your_ahavah.address_for(tx, _token())
            if your_ahavah.is_member(tx, who['email'], who['normalized_email']):
                raise your_ahavah.YourAhavahError('member', 409)
        # Outside a transaction: the network check opens its own.
        if sign_up_closed_to(who['email']):
            raise your_ahavah.YourAhavahError('refused', 403)
        with api_tx() as tx:
            out = your_ahavah.start_profile(tx, _token(), source=req.source, inviter_code=req.inviter_code)
    except your_ahavah.YourAhavahError as e:
        return _refused(e)
    return out, 200, _NO_STORE


@post('/your-ahavah/delete')
def post_your_ahavah_delete():
    """Delete everything under this email, and end the session."""
    from service import your_ahavah
    from service.hard_delete import delete_covers
    try:
        with api_tx() as tx:
            who = your_ahavah.address_for(tx, _token())
            covers = your_ahavah.erase(tx, who['email'], who['normalized_email'])
    except your_ahavah.YourAhavahError as e:
        return _refused(e)
    delete_covers(covers)
    return dict(deleted=True), 200, _NO_STORE


@delete('/your-ahavah/session')
def delete_your_ahavah_session():
    from service import your_ahavah
    with api_tx() as tx:
        your_ahavah.end_session(tx, _token())
    return {}, 200, _NO_STORE
