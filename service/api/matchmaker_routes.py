"""Matchmaker, the member and visitor routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as events_routes is.
Every route but /matchmaker/status answers 404 while matchmaker_live is
off; each surface's routes answer 404 until its own switch is on too.
The mentor's routes live in service/api/mentor_routes.py, the admin's in
service/api/admin/matchmaker_routes.py.
"""
from __future__ import annotations

import re

from flask import request

import duotypes as t
from service.api.decorators import (
    adelete,
    aget,
    apost,
    aput,
    app,
    get,
    limiter,
    post,
    shared_recipient_limit,
    validate,
)

_NO_STORE = {'Cache-Control': 'no-store'}


def _off():
    return dict(error='not_found'), 404


def _refused(e):
    return dict(error=e.reason, **e.extra), e.status, _NO_STORE


# Every path a matchmaker route lives under. While matchmaker_live is off
# they all answer 404 before anything else runs (the body check, the
# limits, the session lookup), so a dark release says nothing about itself.
# Each route checks again, for a call that does not come through a request.
# The check goes first among the app's before_request functions, ahead of
# Flask-Limiter's, so a dark call is never counted or answered 429.
_DARK_PATHS = ('/matchmaker', '/alerts', '/introductions', '/recommendations', '/mentor')
_DARK_PATTERNS = (re.compile(r'^/conversations/[^/]+/(share|sharing)$'),
                  re.compile(r'^/matches/[^/]+/mentor-note$'))


def _matchmaker_dark():
    path = request.path.rstrip('/') or '/'
    if path == '/matchmaker/status':
        return None
    dark = (any(path == p or path.startswith(p + '/') for p in _DARK_PATHS)
            or any(r.match(path) for r in _DARK_PATTERNS))
    if dark:
        from service.matchmaker import live
        if not live():
            return _off()
    return None


app.before_request_funcs.setdefault(None, []).insert(0, _matchmaker_dark)


@get('/matchmaker/status')
def get_matchmaker_status():
    """What the web needs before it shows a matchmaker surface.
    `light_sign_in` is "Your Ahavah" (in-app plan, release 4), served under
    /your-ahavah (service/api/your_ahavah_routes.py)."""
    from service.matchmaker import live, surface_on
    from service.your_ahavah import on as light_sign_in_on
    return (dict(live=live(), alerts=surface_on('matchmaker_alerts'),
                 visitor_alerts=surface_on('matchmaker_visitor_alerts'),
                 introductions=surface_on('matchmaker_introductions'),
                 mentors=surface_on('matchmaker_mentors'),
                 light_sign_in=light_sign_in_on()),
            200, _NO_STORE)


# ---------------------------------------------------------------------------
# A member's alert (1.1 to 1.10). Member session; 404 until matchmaker_alerts.
# ---------------------------------------------------------------------------

def _member_call(surface: str, fn, *, status: int = 200, isolation: str = 'REPEATABLE READ'):
    """Runs fn(tx) for a member's route, answering 404 while the surface is
    dark and the refusal's status otherwise. Pushes the call decides go
    only after its transaction commits."""
    from database import api_tx
    from service.matchmaker import MatchmakerError, surface_on
    from service.matchmaker.mail import collect_pushes
    if not surface_on(surface):  # type: ignore[arg-type]
        return _off()
    try:
        with collect_pushes():
            with api_tx(isolation) as tx:
                out = fn(tx)
    except MatchmakerError as e:
        return _refused(e)
    return out, status, _NO_STORE


@aget('/matchmaker/alert')
def get_matchmaker_alert(s: t.SessionInfo):
    from service.matchmaker import alerts
    return _member_call('matchmaker_alerts', lambda tx: alerts.member_alert(tx, s.person_id))


@aput('/matchmaker/alert')
@validate(t.PutMemberAlert)
def put_matchmaker_alert(req: t.PutMemberAlert, s: t.SessionInfo):
    from service.matchmaker import alerts
    return _member_call('matchmaker_alerts', lambda tx: alerts.save_member_alert(
        tx, s.person_id, req.criteria, notify_push=req.notify_push, notify_email=req.notify_email))


@apost('/matchmaker/alert/pause')
def post_matchmaker_alert_pause(s: t.SessionInfo):
    from service.matchmaker import alerts
    return _member_call('matchmaker_alerts', lambda tx: alerts.pause(tx, s.person_id))


@apost('/matchmaker/alert/resume')
def post_matchmaker_alert_resume(s: t.SessionInfo):
    from service.matchmaker import alerts
    return _member_call('matchmaker_alerts', lambda tx: alerts.resume(tx, s.person_id))


@adelete('/matchmaker/alert')
def delete_matchmaker_alert(s: t.SessionInfo):
    from service.matchmaker import alerts
    return _member_call('matchmaker_alerts', lambda tx: alerts.delete_member_alert(tx, s.person_id))


# ---------------------------------------------------------------------------
# A visitor's alert (3.1 to 3.9). No account; 404 until matchmaker_visitor_
# alerts, except the stop link, which works while live whatever the
# surfaces, so a link in an email always stops it.
# ---------------------------------------------------------------------------

_visitor_ip_limit = limiter.shared_limit('10 per hour; 30 per day', scope='mm_visitor_alert')


@post('/alerts', limiter=[_visitor_ip_limit, shared_recipient_limit])
@validate(t.PostVisitorAlert)
def post_alerts(req: t.PostVisitorAlert):
    """The landing's "Not ready to join?" form. A refused address (the free
    defences), a member's address, an address whose alert is on and one
    past its resend limit all get the same answer as a sent one."""
    from database import api_tx
    from service import leads, signupguard
    from service.matchmaker import MatchmakerError, alerts, clean_first_name, surface_on
    if not surface_on('matchmaker_visitor_alerts'):
        return _off()
    cleaned = leads.clean_email(req.email)
    if cleaned is None:
        return dict(error='bad_email'), 400, _NO_STORE
    try:
        first = clean_first_name(req.first_name)
        criteria = dict(looking_for=req.looking_for, age_min=req.age_min, age_max=req.age_max,
                        region=req.region)
        from service.matchmaker.criteria import clean_visitor_criteria
        clean_visitor_criteria(criteria)
    except MatchmakerError as e:
        return _refused(e)
    # mail_refusal opens its own read, so it runs before the transaction.
    refusal = leads.mail_refusal(email=cleaned[0], ip=request.remote_addr,
                                 stamp=req.signup_stamp, website=req.website)
    if refusal:
        signupguard.record_refusal(refusal, new_address=True, email=cleaned[0],
                                   ip=request.remote_addr)
        return dict(state='check_email', email=cleaned[0]), 201, _NO_STORE
    try:
        with api_tx() as tx:
            out = alerts.ask(tx, email=cleaned[0], criteria=criteria, first_name=first)
    except MatchmakerError as e:
        return _refused(e)
    return out, 201, _NO_STORE


@post('/alerts/confirm')
@validate(t.PostAlertToken)
def post_alerts_confirm(req: t.PostAlertToken):
    """Called by the web page's script, never by the emailed link itself,
    so a mail scanner opening the link confirms nothing."""
    from database import api_tx
    from service.matchmaker import MatchmakerError, alerts, surface_on
    if not surface_on('matchmaker_visitor_alerts'):
        return _off()
    try:
        with api_tx('read committed') as tx:
            out = alerts.confirm(tx, req.token)
    except MatchmakerError as e:
        return _refused(e)
    return out, 200, _NO_STORE


@post('/alerts/stop')
@validate(t.PostAlertToken)
def post_alerts_stop(req: t.PostAlertToken):
    from database import api_tx
    from service.matchmaker import alerts, live
    if not live():
        return _off()
    with api_tx() as tx:
        out = alerts.stop(tx, req.token)
    return out, 200, _NO_STORE


# ---------------------------------------------------------------------------
# Recommend a single (5a). A member, or a visitor signed in with the code
# (the onboardee session /check-otp leaves). 404 until matchmaker_
# introductions, and while the recommendation email is off: a
# recommendation that could not be sent would keep the single's address.
# ---------------------------------------------------------------------------

def _recommending_on() -> bool:
    from service.matchmaker import surface_on, switch_on
    return surface_on('matchmaker_introductions') and switch_on('matchmaker_recommend_email')


_recommend_ip_limit = limiter.shared_limit('10 per hour', scope='mm_recommend')


def _recommend_sender(tx, s: t.SessionInfo, typed_first_name) -> dict:
    """The sender as service.matchmaker.recommend wants them."""
    from service.leads import clean_email
    from service.matchmaker import MatchmakerError, address_key, clean_first_name, first_name
    if s.person_id is not None:
        row = tx.execute('SELECT name, normalized_email FROM person WHERE id = %(i)s',
                         dict(i=s.person_id)).fetchone()
        return dict(person_id=s.person_id, first_name=first_name(row['name']),
                    key=address_key(row['normalized_email']), normalized_email=row['normalized_email'])
    cleaned = clean_email(s.email)
    name = clean_first_name(typed_first_name)
    if cleaned is None or name is None:
        raise MatchmakerError('bad_first_name' if cleaned is not None else 'signed_out',
                              400 if cleaned is not None else 401)
    return dict(person_id=None, first_name=name, key=address_key(cleaned[1]),
                normalized_email=cleaned[1])


@apost('/recommendations', expected_onboarding_status=None,
       limiter=[_recommend_ip_limit, shared_recipient_limit])
@validate(t.PostRecommendation)
def post_recommendations(req: t.PostRecommendation, s: t.SessionInfo):
    """5a.4: "Sent" whatever happens next. A refused address (the free
    defences) is answered the same and nothing is written."""
    from database import api_tx
    from service import leads
    from service.matchmaker import MatchmakerError, recommend
    if not _recommending_on():
        return _off()
    if s.person_id is None:
        # A visitor names themselves before anything else is looked at.
        from service.matchmaker import clean_first_name
        try:
            if clean_first_name(req.first_name) is None:
                raise MatchmakerError('bad_first_name', 400)
        except MatchmakerError as e:
            return _refused(e)
    cleaned = leads.clean_email(req.email)
    if cleaned is None:
        return dict(error='bad_email'), 400, _NO_STORE
    # mail_refusal opens its own read, so it runs before the transaction.
    if leads.mail_refusal(email=cleaned[0], ip=request.remote_addr, stamp=req.signup_stamp,
                          website=req.website):
        return dict(state='sent'), 201, _NO_STORE
    try:
        with api_tx('read committed') as tx:
            sender = _recommend_sender(tx, s, req.first_name)
            out = recommend.recommend(tx, sender=sender, email=cleaned[0], note=req.note)
    except MatchmakerError as e:
        return _refused(e)
    return out, 201, _NO_STORE


@aget('/recommendations/allowance', expected_onboarding_status=None)
def get_recommendations_allowance(s: t.SessionInfo):
    """{left, from}: the form's limit state (5a.5)."""
    from database import api_tx
    from service.leads import clean_email
    from service.matchmaker import address_key, recommend
    if not _recommending_on():
        return _off()
    with api_tx('read committed') as tx:
        if s.person_id is not None:
            ne = tx.execute('SELECT normalized_email FROM person WHERE id = %(i)s',
                            dict(i=s.person_id)).fetchone()['normalized_email']
        else:
            cleaned = clean_email(s.email)
            ne = cleaned[1] if cleaned else s.email
        out = recommend.allowance(tx, address_key(ne))
    return out, 200, _NO_STORE


# ---------------------------------------------------------------------------
# Suggest two members (5b) and answer an introduction (5c). Member session;
# 404 until matchmaker_introductions.
# ---------------------------------------------------------------------------

@aget('/introductions/candidates')
def get_introduction_candidates(s: t.SessionInfo):
    from service.matchmaker import introductions
    for_uuid = request.args.get('for') or ''
    q = request.args.get('q') or ''
    return _member_call('matchmaker_introductions', lambda tx: introductions.candidates(
        tx, s.person_id, for_uuid, q), isolation='read committed')


@apost('/introductions')
@validate(t.PostIntroduction)
def post_introductions(req: t.PostIntroduction, s: t.SessionInfo):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions', lambda tx: introductions.suggest(
        tx, s.person_id, req.a_uuid, req.b_uuid, req.note), status=201, isolation='read committed')


@aget('/introductions/allowance')
def get_introductions_allowance(s: t.SessionInfo):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions',
                        lambda tx: introductions.allowance(tx, s.person_id), isolation='read committed')


@aget('/introductions/pending')
def get_introductions_pending(s: t.SessionInfo):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions', lambda tx: introductions.pending(tx, s.person_id),
                        isolation='read committed')


@apost('/introductions/<int:iid>/accept')
def post_introduction_accept(s: t.SessionInfo, iid: int):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions', lambda tx: introductions.respond(
        tx, s.person_id, iid, 'accept'), isolation='read committed')


@apost('/introductions/<int:iid>/decline')
def post_introduction_decline(s: t.SessionInfo, iid: int):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions', lambda tx: introductions.respond(
        tx, s.person_id, iid, 'decline'), isolation='read committed')


@aget('/introductions/told')
def get_introductions_told(s: t.SessionInfo):
    from service.matchmaker import introductions
    return _member_call('matchmaker_introductions',
                        lambda tx: dict(told=introductions.told(tx, s.person_id)))


@aget('/introductions/with/<uuid>')
def get_introduction_with(s: t.SessionInfo, uuid: str):
    from service.matchmaker import MatchmakerError, introductions

    def go(tx):
        out = introductions.context(tx, s.person_id, uuid)
        if out is None:
            raise MatchmakerError('not_found', 404)
        return out
    return _member_call('matchmaker_introductions', go, isolation='read committed')
