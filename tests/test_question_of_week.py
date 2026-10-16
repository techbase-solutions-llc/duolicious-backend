"""The question of the week (growth spec, Scheduler; TEC-1845).

"one 'Question of the week' a week, drawn from the prompt bank in rotation,
on the slot the brand calendar leaves empty". Next ISO week gets one prompt
post on its first day with nothing else scheduled and no rest day, the
least recently posted prompt first. An empty bank, a week with no free
day, or a week past the owner's known calendar queues nothing.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.spotlight.growthposts import queue_question_of_week, week_key
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('growth_schema')

# The real last date the owner's calendar has been read for, kept before any
# test moves it.
_KNOWN_THROUGH = rd.KNOWN_THROUGH


@pytest.fixture
def bank(monkeypatch):
    """Only this test's prompts are active while it runs; every other row's
    `active` is put back afterwards. The tests drive the clock months ahead,
    past the real KNOWN_THROUGH, so the calendar is read far enough for
    them; test_a_week_past_the_known_calendar_queues_nothing puts it back."""
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    with api_tx() as tx:
        was = [r['key'] for r in tx.execute('SELECT key FROM prompt_bank WHERE active').fetchall()]
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE active')
    made: list[str] = []

    def add(text: str, sort: int = 0) -> str:
        key = f'qw-{uuid4().hex[:8]}'
        with api_tx() as tx:
            tx.execute("""INSERT INTO prompt_bank (key, text, category, sort)
                          VALUES (%(k)s, %(t)s, 'test', %(s)s)""", dict(k=key, t=text, s=sort))
        made.append(key)
        return key

    yield add
    with api_tx() as tx:
        tx.execute('DELETE FROM prompt_bank WHERE key = ANY(%(k)s)', dict(k=made))
        tx.execute('UPDATE prompt_bank SET active = TRUE WHERE key = ANY(%(k)s)', dict(k=was))


@pytest.fixture
def keys():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM publishing_queue WHERE request_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM spotlight_revision WHERE request_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM campaign_link WHERE kind = ANY(%(k)s)',
                   dict(k=[f'post:{k}' for k in made]))


def _now(weeks_ahead: int) -> datetime:
    """A clock this many weeks ahead, so each test owns its target week."""
    return datetime.now(timezone.utc) + timedelta(weeks=weeks_ahead)


def _monday_after(now: datetime):
    ahead = (now + timedelta(days=7)).date()
    return ahead - timedelta(days=ahead.weekday())


def _queue(now, keys) -> str | None:
    with api_tx() as tx:
        rk = queue_question_of_week(tx, now=now, created_by='test')
    if rk:
        keys.append(rk)
    return rk


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT kind, platform, status, caption, scheduled_for, payload
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def test_one_question_a_week_is_queued_from_the_bank(bank, keys):
    key = bank('How I keep Sabbath')
    now = _now(21)
    monday = _monday_after(now)
    rk = _queue(now, keys)
    assert rk == f'prompt:{week_key(monday)}'
    rows = _rows(rk)
    assert {(r['kind'], r['status']) for r in rows} == {('prompt', 'awaiting_render')}
    assert rows[0]['caption'].startswith('Question of the week: How I keep Sabbath')
    assert rows[0]['payload'] == dict(prompt_key=key, text='How I keep Sabbath')
    slot = rows[0]['scheduled_for']
    assert monday <= slot.date() <= monday + timedelta(days=6)
    assert slot.time() in (time(12, 0), time(18, 0))


def test_a_second_run_in_the_same_week_changes_nothing(bank, keys):
    bank('The home I hope to build')
    # Wednesday 12:00 UTC of a fixed week, so the second run 6 hours later
    # targets the same week whatever time of day this runs.
    day = _now(24).date()
    wednesday = day - timedelta(days=day.weekday()) + timedelta(days=2)
    now = datetime.combine(wednesday, time(12, 0), timezone.utc)
    first = _queue(now, keys)
    assert first is not None
    assert _queue(now + timedelta(hours=6), keys) == first
    assert len(_rows(first)) == 2


def test_the_bank_rotates_least_recently_posted_first(bank, keys):
    a = bank('The feast I look forward to most, and why', sort=1)
    b = bank('What I am studying in Torah right now', sort=2)
    now = _now(27)
    picked = []
    for week in range(3):
        rk = _queue(now + timedelta(weeks=week), keys)
        picked.append(_rows(rk)[0]['payload']['prompt_key'])
    assert picked == [a, b, a]


def test_an_empty_bank_queues_nothing(bank, keys):
    assert _queue(_now(30), keys) is None


def test_a_day_the_calendar_already_uses_is_left_to_it(bank, keys):
    bank('My family would describe me as')
    now = _now(33)
    monday = _monday_after(now)
    with api_tx() as tx:
        brand = create_candidate(tx, kind='brand', subject_person_id=None, caption='c', created_by='t',
                                 request_key=f'brand:qw-{uuid4().hex[:8]}')
        tx.execute('UPDATE publishing_queue SET scheduled_for = %(w)s WHERE request_key = %(rk)s',
                   dict(w=datetime.combine(monday, time(12, 0), timezone.utc), rk=brand))
    keys.append(brand)
    rk = _queue(now, keys)
    assert _rows(rk)[0]['scheduled_for'].date() != monday


def test_a_rest_day_is_skipped(bank, keys, monkeypatch):
    bank('Something I am learning to do well')
    now = _now(36)
    monday = _monday_after(now)
    monkeypatch.setattr(rd, 'REST_DAYS', (monday,))
    rk = _queue(now, keys)
    assert _rows(rk)[0]['scheduled_for'].date() != monday


def test_a_week_with_no_free_day_queues_nothing(bank, keys, monkeypatch):
    bank('A verse that carried me through my single season')
    now = _now(39)
    monday = _monday_after(now)
    monkeypatch.setattr(rd, 'REST_DAYS', tuple(monday + timedelta(days=i) for i in range(7)))
    assert _queue(now, keys) is None


def test_a_week_past_the_known_calendar_queues_nothing(bank, keys, monkeypatch):
    bank('What I hope my home will feel like')
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', _KNOWN_THROUGH)
    now = datetime.combine(max(date.today(), _KNOWN_THROUGH) + timedelta(days=14),
                           time(12, 0), timezone.utc)
    assert _queue(now, keys) is None


def test_the_cron_does_nothing_until_switched_on(monkeypatch):
    import service.cron.questionofweek as cron
    monkeypatch.setattr(cron, 'ENABLED', False)
    assert asyncio.run(asyncio.wait_for(cron.question_of_week_forever(), timeout=2)) is None
