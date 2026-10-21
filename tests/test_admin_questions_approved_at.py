"""The schedule says when a week was approved (TEC-1845 admin audit, Minor
21). It sent `approved` alone, though question_drop holds approved_at, so
the owner could not tell an old approval from a fresh one."""
from __future__ import annotations

from datetime import datetime

import pytest

from database import api_tx
from service.questions import admin as qa
from tests.test_admin_questions import NOW, SUN, calendar  # noqa: F401

pytestmark = pytest.mark.usefixtures('questions_schema')


def test_an_approved_week_carries_when(calendar, make_question):  # noqa: F811
    q = make_question()
    with api_tx() as tx:
        qa.set_drop(tx, SUN, q['key'], now=NOW)
        qa.approve(tx, [SUN], now=NOW)
        stored = tx.execute('SELECT approved_at FROM question_drop WHERE live_on = %(d)s',
                            dict(d=SUN)).fetchone()['approved_at']
        row = {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}[SUN.isoformat()]
    assert row['approved'] is True
    assert datetime.fromisoformat(row['approved_at']) == stored


def test_an_unapproved_or_empty_week_carries_none(calendar, make_question):  # noqa: F811
    q = make_question()
    with api_tx() as tx:
        qa.set_drop(tx, SUN, q['key'], now=NOW)
        rows = qa.schedule_rows(tx, NOW)
    assert all(r['approved_at'] is None for r in rows)
