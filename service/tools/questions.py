"""The game's questions, as keys (TEC-1845).

Mirrors ahavah-web src/lib/together/questions.ts: the same question keys,
rounds and option keys, in the same order. The words players read live on
the web only; the API checks keys. Each scored question fills a profile
field the scoring engine reads, so a game result and a profile score mean
the same thing. Light questions ("Just for fun") never score. No question
about plural marriage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

ROUNDS = ('sabbath', 'feasts', 'family', 'home', 'moving', 'talk')

FEASTS_SPRING = ('passover', 'unleavened-bread', 'first-fruits', 'shavuot')
FEASTS_AUTUMN = ('trumpets', 'yom-kippur', 'sukkot')


@dataclass(frozen=True)
class Question:
    key: str
    round: str
    options: tuple[str, ...]
    multi: bool = False
    light: bool = False
    long_list: Optional[str] = None  # 'country' or 'language': the web's lists


GAME_QUESTIONS: tuple[Question, ...] = (
    Question('calendar', 'sabbath', ('rabbinic', 'aviv-barley', 'enoch', 'luni-solar',
                                     'observational-new-moon', 'other')),
    Question('torah-walk', 'sabbath', ('learning', 'beginner', 'intermediate', 'experienced')),
    Question('sabbath-afternoon', 'sabbath', ('walk', 'guests', 'study', 'quiet'), light=True),
    Question('spring-feasts', 'feasts', FEASTS_SPRING, multi=True),
    Question('autumn-feasts', 'feasts', FEASTS_AUTUMN, multi=True),
    Question('favourite-feast', 'feasts', FEASTS_SPRING + FEASTS_AUTUMN, light=True),
    Question('has-children', 'family', ('yes', 'no')),
    Question('children-hope', 'family', ('yes', 'open-to-more', 'large-family', 'blended', 'no')),
    Question('city-or-country', 'home', ('city', 'country')),
    Question('homestead', 'home', ('homestead', 'off-grid', 'neither')),
    Question('community', 'home', ('yes', 'no')),
    Question('sabbath-host', 'home', ('me', 'spouse', 'both', 'less-tired'), light=True),
    Question('country', 'moving', (), long_list='country'),
    Question('move', 'moving', ('will-relocate', 'wants-partner-willing', 'local-only',
                                'international-open')),
    Question('languages', 'moving', (), multi=True, long_list='language'),
    Question('pace', 'talk', ('frequent', 'slow-paced-courtship')),
    Question('talk-how', 'talk', ('video-calls', 'texting', 'in-person'), multi=True),
)

BY_KEY = {q.key: q for q in GAME_QUESTIONS}
SCORED_KEYS = tuple(q.key for q in GAME_QUESTIONS if not q.light)

LANGUAGES_MAX = 10
_COUNTRY = re.compile(r'^[A-Z]{2}$')
_LANGUAGE = re.compile(r'^[a-z]{2,3}$')


def clean_game_answer(key: str, answer: Any) -> Any:
    """The answer as it is stored: an option key, or a list of them with
    repeats dropped and the order kept. Raises ValueError('bad_question')
    for a key the game does not ask, ValueError('bad_answer') for anything
    else that is not one of its options."""
    q = BY_KEY.get(key)
    if q is None:
        raise ValueError('bad_question')
    if q.multi:
        if not isinstance(answer, list) or not answer or len(answer) > LANGUAGES_MAX:
            raise ValueError('bad_answer')
        if q.long_list == 'language':
            ok = all(isinstance(a, str) and _LANGUAGE.match(a) for a in answer)
        else:
            ok = all(isinstance(a, str) and a in q.options for a in answer)
        if not ok:
            raise ValueError('bad_answer')
        out: list[str] = []
        for a in answer:
            if a not in out:
                out.append(a)
        return out
    if q.long_list == 'country':
        if not isinstance(answer, str) or not _COUNTRY.match(answer):
            raise ValueError('bad_answer')
        return answer
    if not isinstance(answer, str) or answer not in q.options:
        raise ValueError('bad_answer')
    return answer
