"""A week that already holds a drop keeps that drop's day (TEC-1933).

Correcting the owner's calendar on 26 Oct 2026 moved the drop day of the
weeks of 25 Oct and 1 Nov from Tuesday to Monday. A drop approved before the
correction, on the old Tuesday, still goes live for members (the current
question is the latest approved drop). The admin schedule has to show it in
its week, propose nothing else for that week, and let the owner edit it.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.questions import admin as qa

pytestmark = pytest.mark.usefixtures('questions_schema')

SUN = date(2027, 3, 7)
OLD_DAY = SUN + timedelta(days=2)  # the Tuesday the drop was approved for
NEW_DAY = SUN + timedelta(days=1)  # the Monday the corrected calendar gives
NOW = datetime.combine(SUN - timedelta(days=2), time(15), timezone.utc)


@pytest.fixture
def calendar(monkeypatch):
    # Only the Sunday rests, so the week's drop day is Monday.
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2027, 12, 31))
    monkeypatch.setattr(rd, 'REST_DAYS', (SUN,))
    window = dict(a=SUN - timedelta(days=7), b=SUN + timedelta(days=70))
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)
    yield
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)


def _approved_drop(day, key):
    with api_tx() as tx:
        tx.execute("INSERT INTO question_drop (live_on, prompt_key, approved_at) VALUES (%(d)s, %(k)s, NOW())",
                   dict(d=day, k=key))


def test_the_schedule_shows_an_existing_drop_on_its_own_day(calendar, make_question):
    q = make_question()
    _approved_drop(OLD_DAY, q['key'])
    with api_tx() as tx:
        rows = qa.schedule_rows(tx, NOW)
    week = next(r for r in rows if r['week_of'] == SUN.isoformat())
    assert week['live_on'] == OLD_DAY.isoformat()
    assert week['prompt_key'] == q['key']
    assert week['approved'] is True
    assert week['proposed_key'] is None


def test_an_empty_week_still_uses_the_corrected_day(calendar):
    with api_tx() as tx:
        rows = qa.schedule_rows(tx, NOW)
    week = next(r for r in rows if r['week_of'] == SUN.isoformat())
    assert week['live_on'] == NEW_DAY.isoformat()


def test_the_owner_can_still_edit_or_clear_the_kept_drop(calendar, make_question):
    q1, q2 = make_question(), make_question()
    _approved_drop(OLD_DAY, q1['key'])
    with api_tx() as tx:
        qa.set_drop(tx, OLD_DAY, q2['key'], NOW)
        assert tx.execute('SELECT prompt_key FROM question_drop WHERE live_on = %(d)s',
                          dict(d=OLD_DAY)).fetchone()['prompt_key'] == q2['key']
        qa.clear_drop(tx, OLD_DAY, NOW)
        assert tx.execute('SELECT 1 FROM question_drop WHERE live_on = %(d)s', dict(d=OLD_DAY)).fetchone() is None


def test_a_day_with_no_drop_that_is_not_the_drop_day_is_still_refused(calendar, make_question):
    q = make_question()
    with api_tx() as tx:
        with pytest.raises(qa.ScheduleRefused) as e:
            qa.set_drop(tx, OLD_DAY, q['key'], NOW)
    assert e.value.args[0] == 'not_a_drop_day'
