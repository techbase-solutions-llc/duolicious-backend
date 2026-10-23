"""Migration 0077, push_tap takes the matchmaker pushes' sources (TEC-1845;
plan 2026-10-22, fix 11). Idempotent, as the deploy may run it more than
once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0077_push_tap_matchmaker_sources.sql').read_text(
    encoding='utf-8')


def test_runs_twice():
    with api_tx() as tx:
        tx.execute(SQL)
        tx.execute(SQL)


def test_the_check_takes_the_new_sources_and_still_refuses_others(make_person):
    p = make_person(name='TapCheck')
    with api_tx() as tx:
        for src in ('qpush', 'mpush', 'lpush', 'mmalert', 'mmintro', 'mmtold'):
            tx.execute('INSERT INTO push_tap (person_id, src) VALUES (%(p)s, %(s)s)', dict(p=p['id'], s=src))
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO push_tap (person_id, src) VALUES (%(p)s, 'email')", dict(p=p['id']))
