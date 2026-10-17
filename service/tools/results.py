"""The Me archetype, knows-me guesses and the board (TEC-1845).

Spec, Me: "an archetype from your strongest axes". With no second person
there is nothing to score against, so each archetype earns points from
the player's own answers in its round (the plan's table, approved by the
owner with the archetypes). Whole numbers, so ties are exact, and ties go
to the export's order. "Why this fits you" names the archetype's round and
the next strongest, so the result reads as what the player said. No
archetype draws on plural marriage.

Who knows me best: a friend's guess is right when it equals the player's
answer (a multiple choice as a set). Only the scored questions the player
answered count; light questions are guessed for fun.
"""
from __future__ import annotations

from typing import Any

from service.tools.questions import BY_KEY, SCORED_KEYS
from service.tools.scoring import js_round

ARCHETYPES = ('sabbath', 'feast', 'family', 'builder', 'student', 'peace', 'explorer', 'bridge')

_FAMILY = {'large-family': 10, 'yes': 7, 'open-to-more': 7, 'blended': 6}
_STUDENT = {'learning': 8, 'beginner': 8, 'intermediate': 5, 'experienced': 3}
_PACE = {'frequent': 4, 'slow-paced-courtship': 2}
_EXPLORER = {'international-open': 10, 'will-relocate': 8}


def points(answers: dict[str, Any]) -> dict[str, int]:
    cal = answers.get('calendar')
    feasts = set(answers.get('spring-feasts') or []) | set(answers.get('autumn-feasts') or [])
    languages = len(answers.get('languages') or [])
    return {
        'sabbath': 6 if cal and cal != 'other' else (3 if cal == 'other' else 0),
        'feast': js_round(10 * len(feasts) / 7),
        'family': min(10, _FAMILY.get(answers.get('children-hope'), 0)
                      + (1 if answers.get('has-children') == 'yes' else 0)),
        'builder': ((5 if answers.get('homestead') in ('homestead', 'off-grid') else 0)
                    + (3 if answers.get('community') == 'yes' else 0)
                    + (2 if answers.get('city-or-country') == 'country' else 0)),
        'student': _STUDENT.get(answers.get('torah-walk'), 0),
        'peace': min(10, _PACE.get(answers.get('pace'), 0) + 2 * len(answers.get('talk-how') or [])),
        'explorer': _EXPLORER.get(answers.get('move'), 0),
        'bridge': 10 if languages >= 3 else (8 if languages == 2 else 0),
    }


def archetype_for(answers: dict[str, Any]) -> tuple[str, list[str]]:
    pts = points(answers)
    ranked = sorted(ARCHETYPES, key=lambda k: (-pts[k], ARCHETYPES.index(k)))
    top = ranked[0]
    if pts[top] == 0:
        return 'sabbath', []
    why = [top] + [k for k in ranked[1:2] if pts[k] > 0]
    return top, why


def _same(q_key: str, a: Any, b: Any) -> bool:
    if b is None:
        return False
    if BY_KEY[q_key].multi:
        return set(a) == set(b if isinstance(b, list) else [])
    return a == b


def guess_score(owner_answers: dict, guess_answers: dict) -> tuple[int, int]:
    keys = [k for k in SCORED_KEYS if k in owner_answers]
    right = sum(1 for k in keys if _same(k, owner_answers[k], guess_answers.get(k)))
    return right, len(keys)


def board_order(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r['right'], r['finished_at'], r['player_id']))
