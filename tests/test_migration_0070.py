"""Migration 0070 (TEC-1845): unmatch. An unmatched pair is a barrier both
ways, in every predicate a surface asks; a report and a pass keep their own
rules. The deploy may run the file more than once, so every test runs it
twice first."""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from database import api_tx

_MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0070_unmatch.sql'


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply()
    _apply()


def _unmatched(tx, a: dict, b: dict, by: dict) -> None:
    tx.execute(
        """INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by)
           VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s), %(by)s)""",
        dict(a=a['id'], b=b['id'], by=by['id']))


def _ask(tx, fn: str, x: dict, y: dict) -> bool:
    return tx.execute(f'SELECT {fn}(%(x)s, %(y)s) AS v', dict(x=x['id'], y=y['id'])).fetchone()['v']


def test_an_unmatch_is_a_barrier_both_ways(unmatch_pair):
    a, b = unmatch_pair.a, unmatch_pair.b
    with api_tx() as tx:
        assert not _ask(tx, 'is_blocked_pair', a, b)
        _unmatched(tx, a, b, a)
        for fn in ('is_unmatched_pair', 'is_blocked_pair', 'is_deck_suppressed'):
            assert _ask(tx, fn, a, b), fn
            assert _ask(tx, fn, b, a), fn


def test_a_pass_and_a_report_keep_their_rules(unmatch_pair):
    a, b = unmatch_pair.a, unmatch_pair.b
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO skipped (subject_person_id, object_person_id, reported)
               VALUES (%(a)s, %(b)s, FALSE)""", dict(a=a['id'], b=b['id']))
        assert not _ask(tx, 'is_blocked_pair', a, b)
        assert _ask(tx, 'is_deck_suppressed', a, b)
        assert not _ask(tx, 'is_deck_suppressed', b, a), 'a pass is one-directional (0036)'
        tx.execute(
            """UPDATE skipped SET reported = TRUE
                WHERE subject_person_id = %(a)s AND object_person_id = %(b)s""",
            dict(a=a['id'], b=b['id']))
        assert _ask(tx, 'is_blocked_pair', b, a)
        assert _ask(tx, 'is_deck_suppressed', b, a)


def test_the_pair_is_stored_once_lower_id_first(unmatch_pair):
    a, b = unmatch_pair.a, unmatch_pair.b
    lo, hi = sorted((a['id'], b['id']))
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by)
                   VALUES (%(hi)s, %(lo)s, %(hi)s)""", dict(lo=lo, hi=hi))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            _unmatched(tx, a, b, a)
            _unmatched(tx, b, a, b)


def test_only_one_of_the_two_can_have_unmatched(unmatch_pair, make_person):
    other = make_person(name='Bystander')
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            _unmatched(tx, unmatch_pair.a, unmatch_pair.b, other)


def test_the_pair_goes_with_either_account(make_person):
    leaving, staying = make_person(name='Leaving'), make_person(name='Staying')
    with api_tx() as tx:
        _unmatched(tx, leaving, staying, leaving)
        tx.execute('DELETE FROM person WHERE id = %(i)s', dict(i=leaving['id']))
        n = tx.execute(
            'SELECT count(*) AS n FROM unmatched_pair WHERE %(s)s IN (user_a_id, user_b_id)',
            dict(s=staying['id'])).fetchone()['n']
    assert n == 0
