"""The Me archetype, knows-me guesses and the board (TEC-1845)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from service.tools import results

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}


def test_the_feast_host_case_matches_the_export():
    # The export's Me result (4.1): The Feast Host, why "The feasts" and
    # "Family and children".
    assert results.archetype_for(CASES['identical']['owner']) == ('feast', ['feast', 'family'])


def test_ties_go_to_the_export_order():
    # family, builder, student and peace all score 8 here.
    assert results.points(CASES['order-matters']['owner'])['family'] == 8
    assert results.archetype_for(CASES['order-matters']['owner']) == ('family', ['family', 'builder'])


def test_no_answers_gives_the_sabbath_keeper_with_no_why():
    assert results.archetype_for({}) == ('sabbath', [])
    assert results.archetype_for({'sabbath-host': 'both'}) == ('sabbath', [])


@pytest.mark.parametrize('answers,want', [
    ({'calendar': 'enoch'}, 'sabbath'),
    ({'spring-feasts': ['passover', 'unleavened-bread', 'first-fruits', 'shavuot'],
      'autumn-feasts': ['trumpets', 'yom-kippur', 'sukkot']}, 'feast'),
    ({'children-hope': 'large-family'}, 'family'),
    ({'homestead': 'homestead', 'community': 'yes', 'city-or-country': 'country'}, 'builder'),
    ({'torah-walk': 'learning'}, 'student'),
    ({'pace': 'frequent', 'talk-how': ['video-calls', 'texting', 'in-person']}, 'peace'),
    ({'move': 'international-open'}, 'explorer'),
    ({'languages': ['en', 'es', 'fr']}, 'bridge'),
])
def test_every_archetype_can_be_reached(answers, want):
    key, why = results.archetype_for(answers)
    assert key == want and why == [want]


def test_a_friend_scores_right_answers_of_the_questions_the_player_answered():
    owner = CASES['order-matters']['owner']
    guess = dict(owner)
    guess['talk-how'] = ['texting', 'video-calls']        # same set: right
    guess['move'] = 'local-only'                           # wrong
    guess.pop('country')                                   # skipped: wrong
    assert results.guess_score(owner, guess) == (12, 14)


def test_light_questions_and_skips_are_left_out_of_the_total():
    owner = {'calendar': 'enoch', 'move': 'local-only', 'pace': 'frequent',
             'sabbath-host': 'both'}
    guess = {'calendar': 'enoch', 'move': 'local-only', 'sabbath-host': 'both'}
    assert results.guess_score(owner, guess) == (2, 3)


def test_the_board_ranks_by_score_then_who_finished_first():
    t = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rows = [dict(player_id=1, right=10, finished_at=t),
            dict(player_id=2, right=12, finished_at=t + timedelta(minutes=5)),
            dict(player_id=3, right=12, finished_at=t)]
    assert [r['player_id'] for r in results.board_order(rows)] == [3, 2, 1]
