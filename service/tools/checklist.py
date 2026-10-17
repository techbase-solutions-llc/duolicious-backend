"""The marriage checklist, version 2: answers and the comparison (TEC-1845).

The passages are today's (ahavah-web src/app/marriage-checklist/content.ts),
with Exodus 21:10-11 for the husband only, as today (owner decision 9).
A stored answer has the shape of duotypes.MarriageChecklistAnswer, so the
existing summary email reads it unchanged. Comments and own items are free
text the player wrote: they show to the other player in the comparison
(export 6.6 and 6.8) and nowhere else, and every email escapes them.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import ValidationError

PASSAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    'p1': ('Genesis 2:18-24', ('husband', 'wife')),
    'p2': ('Exodus 21:10-11', ('husband',)),
    'p3': ('Proverbs 5:15-19', ('husband', 'wife')),
    'p4': ('1 Corinthians 7:2-5', ('husband', 'wife')),
    'p5': ('Ephesians 5:22-33', ('husband', 'wife')),
    'p6': ('Colossians 3:18-19', ('husband', 'wife')),
    'p7': ('1 Peter 3:1-7', ('husband', 'wife')),
    'p8': ('Malachi 2:14-16', ('husband', 'wife')),
    'p9': ('Hebrews 13:4', ('husband', 'wife')),
}
_OWN = re.compile(r'^own-[a-z0-9-]{6,40}$')
_ORDER = {k: i for i, k in enumerate(PASSAGES)}
OWN_PER_SECTION = 20
_SIDE = ('importance', 'stance', 'frequency', 'comment', 'examples', 'other_note')


def clean_checklist_answer(key: str, answer: Any, role: Optional[str]) -> dict:
    from duotypes import MarriageChecklistAnswer
    if key in PASSAGES:
        if role is None:
            raise ValueError('role_required')
        if role not in PASSAGES[key][1]:
            raise ValueError('bad_question')
    elif not _OWN.match(key):
        raise ValueError('bad_question')
    try:
        model = MarriageChecklistAnswer.model_validate(answer)
    except ValidationError:
        raise ValueError('bad_answer')
    data = model.model_dump(exclude_none=True)
    data['examples'] = [e.strip() for e in data.get('examples', []) if e and e.strip()]
    if not data['examples']:
        data.pop('examples')
    for field in ('comment', 'other_note', 'title'):
        if field in data:
            data[field] = data[field].strip()
            if not data[field]:
                data.pop(field)
    if key in PASSAGES:
        if data['section'] != 'biblical' or 'stance' not in data:
            raise ValueError('bad_answer')
        data.pop('title', None)
        data.pop('ref', None)
    else:
        if data['section'] == 'biblical' or not data.get('title'):
            raise ValueError('bad_answer')
        data.pop('ref', None)
    return data


def _side(a: dict) -> dict:
    return {k: a[k] for k in _SIDE if k in a}


def _own(answers: dict) -> list[dict]:
    items = [dict(key=k, **a) for k, a in answers.items() if k.startswith('own-')]
    items.sort(key=lambda i: (i['section'] != 'nice-to-have', -i['importance'], i['key']))
    return items


def compare(owner: dict, guest: dict) -> dict:
    shared = sorted((k for k in PASSAGES if k in owner and k in guest), key=_ORDER.get)
    agree_items, talk_items = [], []
    for k in shared:
        a, b = owner[k], guest[k]
        item = dict(key=k, ref=PASSAGES[k][0], owner=_side(a), guest=_side(b))
        if a.get('stance') != b.get('stance'):
            talk_items.append(dict(item, tag='stance'))
        elif abs(a['importance'] - b['importance']) >= 2:
            talk_items.append(dict(item, tag='importance'))
        else:
            agree_items.append(item)
    return dict(agree=len(agree_items), total=len(shared), agree_items=agree_items,
                talk_items=talk_items, own=dict(owner=_own(owner), guest=_own(guest)))


def top_items(answers: dict, n: int = 3) -> list[dict]:
    """The single's "What matters most to you": scripture and own
    nice-to-haves by importance; challenges are obstacles, not hopes."""
    items = []
    for k, a in answers.items():
        if k in PASSAGES:
            items.append(dict(key=k, ref=PASSAGES[k][0], importance=a['importance'],
                              order=_ORDER[k]))
        elif a.get('section') == 'nice-to-have':
            items.append(dict(key=k, title=a['title'], importance=a['importance'], order=100))
    items.sort(key=lambda i: (-i['importance'], i['order'], i['key']))
    return [{k: v for k, v in i.items() if k != 'order'} for i in items[:n]]


def to_summary_answers(answers: dict) -> list[dict]:
    """The answers as emails.marriage_checklist.checklist_results_html
    takes them: scripture with its reference, own items with their title."""
    out = []
    for k in sorted(answers, key=lambda k: (_ORDER.get(k, 100), k)):
        a = dict(answers[k])
        if k in PASSAGES:
            a['ref'] = PASSAGES[k][0]
        out.append(a)
    return out
