"""Quick questions, the member routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as notifications_routes
is. Every route needs a signed-in member.
"""
import duotypes as t

from database import api_tx
from service.api.decorators import aget, apost, aput, validate


@aput('/answers/<key>')
@validate(t.PutAnswer)
def put_answer(req: t.PutAnswer, s: t.SessionInfo, key: str):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.bank import AnswerRefused, save_answer
    try:
        with api_tx() as tx:
            return save_answer(tx, s.person_id, key, req.choice_key,
                               keep_existing=req.keep_existing)
    except AnswerRefused as e:
        reason = str(e)
        return dict(error=reason), (404 if reason == 'closed' else 400)


@aget('/answers')
def get_answers(s: t.SessionInfo):
    """The member's own answers, for their own profile."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.bank import my_answers
    with api_tx('read committed') as tx:
        return dict(answers=my_answers(tx, s.person_id))


@aget('/questions/current')
def get_current_question(s: t.SessionInfo):
    """This week's question, the member's answer and the split once there
    are 5 answers and the member has given one."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import current_for
    with api_tx('read committed') as tx:
        return current_for(tx, s.person_id)


@aget('/questions/catch-up')
def get_catch_up(s: t.SessionInfo):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import catch_up_for
    with api_tx('read committed') as tx:
        return catch_up_for(tx, s.person_id)


@apost('/questions/catch-up/decline')
def post_catch_up_decline(s: t.SessionInfo):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import decline_catch_up
    with api_tx() as tx:
        decline_catch_up(tx, s.person_id)
    return '', 204


@aget('/conversation-context/<prospect_uuid>')
def get_conversation_context(s: t.SessionInfo, prospect_uuid: str):
    """The chat block of a match (spec, API): the match question, whether
    the other member has answered and both answers once both have.

    Read committed: the first open assigns the match question with
    INSERT ... ON CONFLICT DO NOTHING, and when both members open the chat
    at once, REPEATABLE READ fails the second with a serialisation error.
    Here it waits, does nothing, and reads the question the first chose."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import conversation_context
    with api_tx('read committed') as tx:
        ctx = conversation_context(tx, s.person_id, prospect_uuid)
    return ctx if ctx is not None else ('', 404)


# One row per member and source per 10 minutes, so a reload or a second
# tab does not count twice.
_Q_TAP = """
    INSERT INTO push_tap (person_id, src)
    SELECT %(p)s, %(s)s
     WHERE NOT EXISTS (SELECT 1 FROM push_tap
                        WHERE person_id = %(p)s AND src = %(s)s
                          AND tapped_at > NOW() - interval '10 minutes')
"""


@apost('/push-taps')
@validate(t.PostPushTap)
def post_push_tap(req: t.PostPushTap, s: t.SessionInfo):
    """Nothing recorded a push tap before this (spec, Notifications): the
    web reads only utm keys and sw.js only opens the URL."""
    if s.person_id is None:
        return 'Not signed in', 401
    with api_tx() as tx:
        tx.execute(_Q_TAP, dict(p=s.person_id, s=req.src))
    return '', 204
