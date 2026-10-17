"""The game's scoring: a port of ahavah-web src/lib/scoring (TEC-1845).

Spec: "Reuses the existing engine (compute-compatibility.ts, 9 axes). ...
The plural marriage axis has weight 0 and no question. The rules are
ported to Python in the API, with a cross-repo test that both copies give
identical scores for the same answers ... so a stored result is computed
on the server and cannot be tampered with."

Each rule below is the TypeScript rule of the same name, line for line,
and returns a number from 0 to 1. Change one only with its twin and the
shared fixture (tests/fixtures/together_scoring_cases.json). JavaScript's
Math.round rounds halves up, Python's round() rounds them to even, so the
composite uses js_round. The web's app pill keeps its own weights
(owner decision 8); only the game uses GAME_WEIGHTS.

The language rule divides by the first person's languages, so a game is
always scored with its owner first.
"""
from __future__ import annotations

import math
from typing import Any

from service.tools.questions import ROUNDS

AXES = ('calendar', 'polygyny', 'family', 'relocation', 'lifestyle', 'communication',
        'observance', 'feast', 'language')
# BALANCED with plural marriage at 0: excluded from both sides of the mean.
GAME_WEIGHTS = {axis: (0 if axis == 'polygyny' else 1) for axis in AXES}

# The 8 areas a player sees, in the export's order (Calendar, Torah walk,
# The feasts, Children, Home, Moving, Language, How you talk).
AREAS = ('calendar', 'observance', 'feast', 'family', 'lifestyle', 'relocation', 'language',
         'communication')
# The 6 bars, one per round: the mean of the round's axes.
ROUND_AXES = {
    'sabbath': ('calendar', 'observance'),
    'feasts': ('feast',),
    'family': ('family',),
    'home': ('lifestyle',),
    'moving': ('relocation', 'language'),
    'talk': ('communication',),
}

_LUNI_SOLAR_FAMILY = frozenset({'luni-solar', 'observational-new-moon', 'aviv-barley'})
_PRO_CREATION = ('wants-children', 'has-children', 'open-to-more', 'interested-large-family')
_CORE_FEASTS = frozenset({'passover', 'unleavened-bread', 'first-fruits', 'shavuot',
                          'trumpets', 'yom-kippur', 'sukkot'})
_RANK = {'learning': 0, 'beginner': 1, 'intermediate': 2, 'experienced': 3}
_PROXIMITY = {0: 1.0, 1: 0.8, 2: 0.5, 3: 0.2}
_POLYGYNY = {
    'monogamy-only|monogamy-only': 1.0, 'open|open': 0.9, 'supports|supports': 1.0,
    'undecided|undecided': 0.7, 'open|supports': 0.8, 'monogamy-only|supports': 0.0,
    'supports|undecided': 0.5, 'monogamy-only|open': 0.4, 'open|undecided': 0.6,
    'monogamy-only|undecided': 0.5,
}
_RELOCATION = {
    'will-relocate|will-relocate': 1.0, 'wants-partner-willing|will-relocate': 1.0,
    'local-only|will-relocate': 0.8, 'international-open|will-relocate': 0.9,
    'wants-partner-willing|wants-partner-willing': 0.5, 'local-only|wants-partner-willing': 0.2,
    'international-open|wants-partner-willing': 0.7,
    'international-open|international-open': 1.0, 'international-open|local-only': 0.5,
}
_CHILDREN_HOPE = {'yes': 'wants-children', 'open-to-more': 'open-to-more',
                  'large-family': 'interested-large-family', 'blended': 'open-blended',
                  'no': 'does-not-want'}


def js_round(x: float) -> int:
    """JavaScript's Math.round for the non-negative numbers scores are."""
    return math.floor(x + 0.5)


def _list(profile: dict, field: str) -> list:
    return list(profile.get(field) or [])


def score_calendar(a: dict, b: dict) -> float:
    ca, cb = a.get('calendar'), b.get('calendar')
    if not ca or not cb:
        return 0.3
    if ca == cb:
        return 1.0
    if ca == 'other' or cb == 'other':
        return 0.3
    if ca in _LUNI_SOLAR_FAMILY and cb in _LUNI_SOLAR_FAMILY:
        return 0.7
    return 0.4


def score_polygyny(a: dict, b: dict) -> float:
    pa, pb = a.get('polygyny'), b.get('polygyny')
    if not pa or not pb:
        return 0.5
    return _POLYGYNY['|'.join(sorted((pa, pb)))]


def score_family(a: dict, b: dict) -> float:
    av, bv = _list(a, 'familyViews'), _list(b, 'familyViews')
    if not av and not bv:
        return 0.5
    if not av or not bv:
        return 0.4
    a_dnw, b_dnw = 'does-not-want' in av, 'does-not-want' in bv
    a_pro = any(v in _PRO_CREATION for v in av)
    b_pro = any(v in _PRO_CREATION for v in bv)
    if (a_dnw and b_pro) or (b_dnw and a_pro):
        return 0.0
    aset, bset = set(av), set(bv)
    inter = len(aset & bset)
    union = len(aset | bset)
    base = 0 if union == 0 else inter / union
    return min(base + (0.1 if inter > 0 else 0), 1.0)


def score_relocation(a: dict, b: dict) -> float:
    ra, rb = a.get('relocation'), b.get('relocation')
    if not ra or not rb:
        return 0.5
    if ra == 'local-only' and rb == 'local-only':
        ca, cb = a.get('country'), b.get('country')
        if not ca or not cb:
            return 0.5
        return 1.0 if ca == cb else 0.0
    return _RELOCATION.get('|'.join(sorted((ra, rb))), 0.5)


def score_lifestyle(a: dict, b: dict) -> float:
    pa, pb = _list(a, 'livingPreferences'), _list(b, 'livingPreferences')
    if not pa and not pb:
        return 0.5
    if not pa or not pb:
        return 0.4
    sa, sb = set(pa), set(pb)
    inter = len(sa & sb)
    union = len(sa | sb)
    base = 0 if union == 0 else inter / union
    return min(1.0, base + (0.1 if inter > 0 else 0))


def score_communication(a: dict, b: dict) -> float:
    ap, bp = _list(a, 'communicationPrefs'), _list(b, 'communicationPrefs')
    if not ap and not bp:
        return 0.5
    if not ap or not bp:
        return 0.4
    sa, sb = set(ap), set(bp)
    inter = len(sa & sb)
    union = len(sa | sb)
    base = 0 if union == 0 else inter / union
    conflict = (('frequent' in sa and 'slow-paced-courtship' in sb)
                or ('slow-paced-courtship' in sa and 'frequent' in sb))
    if conflict and inter == 0:
        return 0.2
    return min(base + (0.1 if inter > 0 else 0), 1.0)


def score_observance(a: dict, b: dict) -> float:
    la, lb = a.get('torahLevel'), b.get('torahLevel')
    if not la or not lb:
        return 0.5
    return _PROXIMITY[abs(_RANK[la] - _RANK[lb])]


def score_feast(a: dict, b: dict) -> float:
    sa, sb = set(_list(a, 'feastDays')), set(_list(b, 'feastDays'))
    if not sa and not sb:
        return 0.5
    if not sa or not sb:
        return 0.4
    inter = [f for f in _list(a, 'feastDays') if f in sb]
    inter = list(dict.fromkeys(inter))
    jaccard = len(inter) / len(sa | sb)
    bonus = 0.0
    for f in inter:
        if f in _CORE_FEASTS:
            bonus += 0.05
    bonus = min(0.35, bonus)
    return min(1.0, jaccard + bonus)


def score_language(viewer: dict, candidate: dict) -> float:
    v = _list(viewer, 'languages')
    if not v:
        return 0.0
    c = set(_list(candidate, 'languages'))
    return sum(1 for lang in v if lang in c) / len(v)


_RULES = {
    'calendar': score_calendar, 'polygyny': score_polygyny, 'family': score_family,
    'relocation': score_relocation, 'lifestyle': score_lifestyle,
    'communication': score_communication, 'observance': score_observance,
    'feast': score_feast, 'language': score_language,
}


def compute_compatibility(a: dict, b: dict, weights: dict = GAME_WEIGHTS) -> dict:
    """computeCompatibility(a, b, weights): each axis 0 to 1, and the
    weighted mean of the axes with a weight above 0 as a whole number from
    0 to 100."""
    breakdown = {axis: _RULES[axis](a, b) for axis in AXES}
    weighted = 0.0
    total = 0.0
    for axis in AXES:
        w = weights[axis]
        if w <= 0 or not math.isfinite(breakdown[axis]):
            continue
        weighted += w * breakdown[axis]
        total += w
    normalized = weighted / total if total > 0 else 0
    return dict(score=js_round(normalized * 100), breakdown=breakdown)


def answers_to_profile(answers: dict[str, Any]) -> dict:
    """The profile fields a set of game answers fills (the web's
    answersToProfile). A skipped question leaves its field out, so the
    engine scores it as it scores an empty profile field. Light questions
    fill nothing."""
    p: dict[str, Any] = {}
    if answers.get('calendar'):
        p['calendar'] = answers['calendar']
    if answers.get('torah-walk'):
        p['torahLevel'] = answers['torah-walk']
    feasts = list(answers.get('spring-feasts') or []) + list(answers.get('autumn-feasts') or [])
    if feasts:
        p['feastDays'] = feasts
    family = []
    if answers.get('has-children') == 'yes':
        family.append('has-children')
    if answers.get('children-hope') in _CHILDREN_HOPE:
        family.append(_CHILDREN_HOPE[answers['children-hope']])
    if family:
        p['familyViews'] = family
    living = []
    if answers.get('city-or-country') == 'city':
        living.append('urban')
    elif answers.get('city-or-country') == 'country':
        living.append('rural')
    if answers.get('homestead') in ('homestead', 'off-grid'):
        living.append(answers['homestead'])
    if answers.get('community') == 'yes':
        living.append('community-living')
    if living:
        p['livingPreferences'] = living
    if answers.get('country'):
        p['country'] = answers['country']
    if answers.get('move'):
        p['relocation'] = answers['move']
    if answers.get('languages'):
        p['languages'] = list(answers['languages'])
    comm = []
    if answers.get('pace'):
        comm.append(answers['pace'])
    comm.extend(answers.get('talk-how') or [])
    if comm:
        p['communicationPrefs'] = comm
    return p


def us_result(owner_answers: dict, guest_answers: dict) -> dict:
    """The Us reveal: the score, each area, the 3 areas that align most,
    the 2 worth talking about and a bar per round. Ties go to the order of
    AREAS."""
    r = compute_compatibility(answers_to_profile(owner_answers), answers_to_profile(guest_answers))
    areas = {axis: r['breakdown'][axis] for axis in AREAS}
    align = sorted(AREAS, key=lambda ax: (-areas[ax], AREAS.index(ax)))[:3]
    talk = [ax for ax in sorted(AREAS, key=lambda ax: (areas[ax], AREAS.index(ax)))
            if ax not in align][:2]
    bars = []
    for rnd in ROUNDS:
        axes = ROUND_AXES[rnd]
        bars.append(dict(round=rnd, pct=js_round(sum(areas[ax] for ax in axes) / len(axes) * 100)))
    return dict(score=r['score'], areas={k: round(v, 4) for k, v in areas.items()},
                align=align, talk=talk, bars=bars)
