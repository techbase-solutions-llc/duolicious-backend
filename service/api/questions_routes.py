"""Quick questions, the member routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as notifications_routes
is. Every route needs a signed-in member.
"""
import duotypes as t

from database import api_tx
from service.api.decorators import aget, aput, validate


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
