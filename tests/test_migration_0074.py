"""Migration 0074, a visitor alert's change waits for its link (TEC-1845).
Idempotent, as the deploy may run it more than once."""
from pathlib import Path

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0074_matchmaker_alert_change.sql').read_text(
    encoding='utf-8')


def test_runs_twice():
    with api_tx() as tx:
        tx.execute(SQL)
        tx.execute(SQL)


def test_the_columns():
    with api_tx('read committed') as tx:
        cols = {r['column_name'] for r in tx.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'match_alert'").fetchall()}
    assert {'pending_criteria', 'pending_first_name', 'change_token_hash'} <= cols
