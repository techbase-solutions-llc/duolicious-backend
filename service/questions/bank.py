"""Live questions, one member's answers and the split (TEC-1845).

Release 1 answers are taps on fixed options, never free text, so nothing a
member writes reaches another member. A question is live when it is active
and has a choice format; the open questions wait for release 2.

The split is counts, never percentages, and shows only from SPLIT_MIN
member answers, so a small count cannot point to a person. Staff answers
are not counted. A member sees a split only once they have answered.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from typing import Optional

from service.admin.queries.members import member_sql
from service.questions import live

SPLIT_MIN = 5
CHOICE_FORMATS = ('either_or', 'pick_one')
# SQL: the prompt_bank row aliased b is a live quick question.
LIVE = "b.active AND b.format IN ('either_or', 'pick_one')"


class AnswerRefused(ValueError):
    """'closed': no live question has that key, or the questions are not
    live yet (service.questions.live), so a stale page cannot save.
    'bad_choice': the question does not offer that option."""


_COLS = 'b.key, b.text, b.format, b.options'

_Q_QUESTION = f"SELECT {_COLS} FROM prompt_bank b WHERE b.key = %(k)s AND {LIVE}"

_Q_CHOICE = """
    SELECT choice_key FROM prompt_answer
     WHERE person_id = %(p)s AND prompt_key = %(k)s AND choice_key IS NOT NULL
"""

_Q_COUNTS = f"""
    SELECT a.choice_key, count(*) AS n
      FROM prompt_answer a
      JOIN person p ON p.id = a.person_id
     WHERE a.prompt_key = %(k)s AND a.choice_key IS NOT NULL
       AND p.activated AND {member_sql('p')}
     GROUP BY a.choice_key
"""

_Q_SAVE = """
    INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
    VALUES (%(p)s, %(k)s, %(c)s)
    ON CONFLICT (person_id, prompt_key) DO UPDATE
       SET choice_key = EXCLUDED.choice_key, updated_at = NOW()
"""

# An email click: saves only when nothing is saved yet (spec, Launch).
_Q_SAVE_IF_NEW = """
    INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
    VALUES (%(p)s, %(k)s, %(c)s)
    ON CONFLICT (person_id, prompt_key) DO NOTHING
"""

_Q_MY_ANSWERS = f"""
    SELECT {_COLS}, a.choice_key
      FROM prompt_answer a
      JOIN prompt_bank b ON b.key = a.prompt_key
     WHERE a.person_id = %(p)s AND a.choice_key IS NOT NULL AND {LIVE}
     ORDER BY b.sort, b.key
"""


def question_json(row) -> dict:
    return dict(key=row['key'], text=row['text'], format=row['format'],
                options=[dict(key=o['key'], label=o['label']) for o in row['options']])


def live_question(tx, key: str) -> Optional[dict]:
    row = tx.execute(_Q_QUESTION, dict(k=key)).fetchone()
    return question_json(row) if row else None


def choice_of(tx, person_id: int, key: str) -> Optional[str]:
    row = tx.execute(_Q_CHOICE, dict(p=person_id, k=key)).fetchone()
    return row['choice_key'] if row else None


def split(tx, question: dict) -> Optional[list[dict]]:
    """Counts per option, in the question's order, or None under SPLIT_MIN."""
    got = {r['choice_key']: int(r['n'])
           for r in tx.execute(_Q_COUNTS, dict(k=question['key'])).fetchall()}
    counts = [dict(key=o['key'], n=got.get(o['key'], 0)) for o in question['options']]
    return counts if sum(c['n'] for c in counts) >= SPLIT_MIN else None


def question_state(tx, person_id: int, question: dict) -> dict:
    mine = choice_of(tx, person_id, question['key'])
    return dict(question=question, my_choice=mine,
                counts=split(tx, question) if mine is not None else None)


def save_answer(tx, person_id: int, key: str, choice_key: str, *,
                keep_existing: bool = False) -> dict:
    if not live():
        raise AnswerRefused('closed')
    question = live_question(tx, key)
    if question is None:
        raise AnswerRefused('closed')
    if choice_key not in {o['key'] for o in question['options']}:
        raise AnswerRefused('bad_choice')
    tx.execute(_Q_SAVE_IF_NEW if keep_existing else _Q_SAVE,
               dict(p=person_id, k=key, c=choice_key))
    return question_state(tx, person_id, question)


def my_answers(tx, person_id: int) -> list[dict]:
    return [dict(question=question_json(r), choice_key=r['choice_key'])
            for r in tx.execute(_Q_MY_ANSWERS, dict(p=person_id)).fetchall()]
