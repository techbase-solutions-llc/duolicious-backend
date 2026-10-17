"""The game's scoring, ported from the web (TEC-1845).

Spec: "The rules are ported to Python in the API, with a cross-repo test
that both copies give identical scores for the same answers." Both copies
read tests/fixtures/together_scoring_cases.json; the web's half is
ahavah-web tests/lib/together-scoring-parity.test.ts. The game gives plural
marriage weight 0 and asks nothing about it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.tools import questions, scoring

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json'
CASES = json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_the_port_scores_each_shared_case_as_the_web_engine_does(case):
    a = scoring.answers_to_profile(case['owner'])
    b = scoring.answers_to_profile(case['guest'])
    r = scoring.compute_compatibility(a, b)
    assert r['score'] == case['score']
    assert set(r['breakdown']) == set(case['breakdown'])
    for axis, want in case['breakdown'].items():
        assert r['breakdown'][axis] == pytest.approx(want, abs=1e-9), axis
    if 'reversed_score' in case:
        assert scoring.compute_compatibility(b, a)['score'] == case['reversed_score']


def test_plural_marriage_has_weight_0_and_no_question():
    assert scoring.GAME_WEIGHTS['polygyny'] == 0
    assert all(w == 1 for axis, w in scoring.GAME_WEIGHTS.items() if axis != 'polygyny')
    assert not [q.key for q in questions.GAME_QUESTIONS if 'polyg' in q.key or 'wife' in q.key]
    assert 'polygyny' not in scoring.AREAS
    full = {q.key: (q.options[:1] if q.multi else q.options[0]) for q in questions.GAME_QUESTIONS
            if q.options}
    assert 'polygyny' not in scoring.answers_to_profile(full)


def test_js_round_rounds_halves_up_as_math_round_does():
    assert [scoring.js_round(x) for x in (20.5, 21.5, 58.75, 41.25, 0.0)] == [21, 22, 59, 41, 0]


def test_light_questions_never_score():
    assert scoring.answers_to_profile(
        {'sabbath-afternoon': 'walk', 'favourite-feast': 'sukkot', 'sabbath-host': 'both'}) == {}
    assert questions.SCORED_KEYS == (
        'calendar', 'torah-walk', 'spring-feasts', 'autumn-feasts', 'has-children',
        'children-hope', 'city-or-country', 'homestead', 'community', 'country', 'move',
        'languages', 'pace', 'talk-how')


def test_answers_map_onto_the_profile_fields():
    owner = next(c for c in CASES if c['name'] == 'order-matters')['owner']
    assert scoring.answers_to_profile(owner) == {
        'calendar': 'enoch', 'torahLevel': 'beginner',
        'feastDays': ['passover', 'unleavened-bread', 'first-fruits', 'shavuot', 'trumpets'],
        'familyViews': ['has-children', 'open-to-more'],
        'livingPreferences': ['urban', 'off-grid', 'community-living'],
        'country': 'JM', 'relocation': 'wants-partner-willing', 'languages': ['en'],
        'communicationPrefs': ['frequent', 'video-calls', 'texting'],
    }


@pytest.mark.parametrize('key,answer,reason', [
    ('nope', 'x', 'bad_question'),
    ('calendar', 'julian', 'bad_answer'),
    ('spring-feasts', [], 'bad_answer'),
    ('spring-feasts', ['hanukkah'], 'bad_answer'),
    ('country', 'usa', 'bad_answer'),
    ('languages', ['en', 'es', 'fr', 'de', 'it', 'nl', 'ru', 'pl', 'uk', 'he', 'yi'], 'bad_answer'),
])
def test_a_bad_answer_is_refused(key, answer, reason):
    with pytest.raises(ValueError, match=reason):
        questions.clean_game_answer(key, answer)


def test_a_clean_answer_keeps_order_and_drops_repeats():
    assert questions.clean_game_answer('talk-how', ['texting', 'texting', 'in-person']) == [
        'texting', 'in-person']
    assert questions.clean_game_answer('country', 'BB') == 'BB'


def test_the_us_result_names_areas_and_round_bars():
    case = next(c for c in CASES if c['name'] == 'order-matters')
    r = scoring.us_result(case['owner'], case['guest'])
    assert r['score'] == 59
    assert r['align'] == ['relocation', 'language', 'observance']
    assert r['talk'] == ['family', 'calendar']
    assert r['bars'] == [
        {'round': 'sabbath', 'pct': 55}, {'round': 'feasts', 'pct': 65},
        {'round': 'family', 'pct': 0}, {'round': 'home', 'pct': 35},
        {'round': 'moving', 'pct': 100}, {'round': 'talk', 'pct': 60}]
    assert set(r['areas']) == set(scoring.AREAS)
