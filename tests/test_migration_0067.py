"""Migration 0067: quick questions, release 1 (TEC-1845).

Pins the bank as the owner approved it (14 choice questions active, the
guide's 20 open questions waiting inactive for release 2), the shape rules
the database itself enforces, and that a second run of the file never
overwrites an edit the owner made in Admin > Questions. The deploy may run
the file more than once, so every test runs it twice first.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_DIR = Path(__file__).resolve().parent.parent / 'migrations'


def _apply(name: str) -> None:
    with api_tx() as tx:
        tx.execute((_DIR / name).read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply('0066_growth_foundations.sql')
    _apply('0067_quick_questions.sql')
    _apply('0067_quick_questions.sql')


WYR = 'Would you rather'
MER = 'Mornings, evenings and how you rest'
FAM = 'Family life and traditions'
LIT = 'Little preferences that reveal a lot'

ACTIVE = {
    'host-or-dessert': (WYR, 'either_or', ['Hosting the feast meal', 'Bringing dessert']),
    'mountains-or-sea': (WYR, 'either_or', ['Mountains', 'The sea']),
    'cabin-or-city': (WYR, 'either_or', ['A cabin with no signal', 'A new city to explore']),
    'grow-or-market': (WYR, 'either_or', ['Growing vegetables', 'Knowing every good market stall']),
    'language-or-instrument': (WYR, 'either_or', ['A new language', 'A new instrument']),
    'coffee-or-tea': (MER, 'pick_one', ['Coffee', 'Tea', 'Something else']),
    'morning-or-night': (MER, 'either_or', ['Early mornings', 'Late evenings']),
    'sabbath-afternoon': (MER, 'pick_one', ['A long walk', 'A nap', 'A table full of friends']),
    'people-or-quiet': (MER, 'either_or', ['People', 'Quiet']),
    'family-table': (FAM, 'either_or', ['A big family table', 'Small and cosy']),
    'window-or-aisle': (LIT, 'either_or', ['The window seat', 'The aisle seat']),
    'early-or-late': (LIT, 'pick_one', ['Early', 'On time', 'A little late']),
    'plan-or-decide': (LIT, 'either_or', ['Planning to the hour', 'Deciding on the day']),
    'city-town-or-country': (LIT, 'pick_one', ['The city', 'A small town',
                                               'A long drive to the nearest neighbour']),
}

OPEN = {
    'cook-for-guests', 'feast-food', 'song-every-word', 'book-or-album', 'hobby-to-start',
    'surprisingly-good-at', 'place-to-return', 'first-hour', 'ideal-free-day',
    'ideal-kitchen-table', 'ideal-trip', 'ideal-picnic', 'tradition-to-carry-on', 'best-cook',
    'favourite-feast-gathering', 'family-game', 'pet', 'secret-chore', 'thing-with-a-story',
    'small-good-thing',
}


def _bank() -> dict:
    with api_tx('read committed') as tx:
        rows = tx.execute(
            """SELECT key, text, category, format, options, active FROM prompt_bank
                WHERE key = ANY(%(k)s)""",
            dict(k=[*ACTIVE, *OPEN])).fetchall()
    return {r['key']: dict(r) for r in rows}


def test_the_14_choice_questions_are_seeded_active_with_their_options():
    bank = _bank()
    for key, (category, fmt, labels) in ACTIVE.items():
        row = bank[key]
        assert row['active'] is True, key
        assert (row['category'], row['format']) == (category, fmt), key
        assert [o['label'] for o in row['options']] == labels, key
        assert len({o['key'] for o in row['options']}) == len(labels), key


def test_the_20_open_questions_wait_inactive_for_release_2():
    bank = _bank()
    assert set(OPEN) <= set(bank)
    for key in OPEN:
        assert (bank[key]['format'], bank[key]['active'], bank[key]['options']) == ('text', False, []), key


def test_every_option_reads_inside_a_sentence():
    for key, (_, _, labels) in ACTIVE.items():
        for label in labels:
            words = label.lower().split()
            assert 1 <= len(label) <= 40, label
            assert 'i' not in words and 'my' not in words, label
            assert '\u2014' not in label, label
    assert max(len(r['text']) for r in _bank().values()) <= 120


def test_a_second_run_keeps_the_owners_edits():
    with api_tx() as tx:
        before = tx.execute("SELECT options, active FROM prompt_bank WHERE key = 'mountains-or-sea'").fetchone()
        tx.execute("""UPDATE prompt_bank
                         SET options = jsonb_set(options, '{0,label}', '"Hills"'), active = FALSE
                       WHERE key = 'mountains-or-sea'""")
    try:
        _apply('0067_quick_questions.sql')
        row = _bank()['mountains-or-sea']
        assert row['options'][0]['label'] == 'Hills' and row['active'] is False
    finally:
        with api_tx() as tx:
            tx.execute("UPDATE prompt_bank SET options = %(o)s::jsonb, active = %(a)s WHERE key = 'mountains-or-sea'",
                       dict(o=json.dumps(before['options']), a=before['active']))


@pytest.mark.parametrize('fmt,options', [
    ('either_or', [{'key': 'a', 'label': 'A'}]),
    ('pick_one', [{'key': 'a', 'label': 'A'}, {'key': 'b', 'label': 'B'}]),
    ('pick_one', [{'key': k, 'label': k} for k in 'abcde']),
    ('text', [{'key': 'a', 'label': 'A'}]),
    ('poll', []),
])
def test_the_format_and_its_options_must_agree(fmt, options):
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO prompt_bank (key, text, category, format, options)
                   VALUES (%(k)s, 'x', 'test', %(f)s, %(o)s::jsonb)""",
                dict(k=f'm0067-{uuid4().hex[:8]}', f=fmt, o=json.dumps(options)))


def test_an_answer_names_a_choice_or_a_text(make_person):
    person = make_person(name='M0067')
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO prompt_answer (person_id, prompt_key) VALUES (%(p)s, 'mountains-or-sea')",
                       dict(p=person['id']))
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, 'mountains-or-sea', 'sea')""", dict(p=person['id']))


def test_one_question_per_drop_day():
    day = date(2031, 3, 2)
    try:
        with api_tx() as tx:
            tx.execute("INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, 'mountains-or-sea')", dict(d=day))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, 'window-or-aisle')", dict(d=day))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=day))


def test_a_push_tap_names_a_known_source(make_person):
    person = make_person(name='M0067Tap')
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO push_tap (person_id, src) VALUES (%(p)s, 'email')", dict(p=person['id']))


def test_the_new_columns_and_their_defaults(make_person):
    person = make_person(name='M0067Cols')
    with api_tx() as tx:
        tx.execute('INSERT INTO notification_preference (person_id) VALUES (%(p)s)', dict(p=person['id']))
        pref = tx.execute('SELECT push_questions, push_questions_off_at FROM notification_preference '
                          'WHERE person_id = %(p)s', dict(p=person['id'])).fetchone()
        cols = {(r['table_name'], r['column_name']) for r in tx.execute(
            """SELECT table_name, column_name FROM information_schema.columns
                WHERE (table_name, column_name) IN (('push_subscription', 'tz'),
                      ('person', 'question_catchup_declined_at'), ('match_question', 'prompt_key'))""").fetchall()}
    assert pref['push_questions'] is True and pref['push_questions_off_at'] is None
    assert cols == {('push_subscription', 'tz'), ('person', 'question_catchup_declined_at'),
                    ('match_question', 'prompt_key')}
