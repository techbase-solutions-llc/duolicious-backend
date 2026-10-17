"""The launch push (TEC-1845, spec "Launch").

One line, once per member ever, on a drop day evening while its switch is
on: to members with a subscription and the setting on, whether or not they
have answered or been away, never to one who left campaign emails. It is
that week's question push: it spends the week's budget, so no weekly push
follows. Quiet hours, rest days, the gap and the stop after 2 all apply.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from database import api_tx
from service.campaigns import held
from service.questions import pushes as qp
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema', 'questions_live')

UTC = timezone.utc


@pytest.fixture
def launch_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_QUESTION_PUSH_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    q = make_question(labels=('Mountains', 'The sea'))
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _evening(day) -> datetime:
    return datetime.combine(day, time(18, 30), ZoneInfo('UTC')).astimezone(UTC)


def _run(job, now) -> None:
    with api_tx() as tx:
        job(tx, now)
    held.run_after_commit()


def _to(sent, person) -> list[dict]:
    return [p for p in sent if p['person_id'] == person['id']]


def _logs(person) -> set:
    with api_tx('read committed') as tx:
        return {(r['campaign'], r['campaign_id']) for r in tx.execute(
            'SELECT campaign, campaign_id FROM push_send_log WHERE person_id = %(p)s',
            dict(p=person['id'])).fetchall()}


def test_off_by_default(push_member, pushed_questions, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED', raising=False)
    m = push_member('LaunchOff')
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []


def test_the_launch_push_goes_once_on_a_drop_day_evening(push_member, pushed_questions, week, launch_on):
    m = push_member('Launch')
    live_on = week['today'].isoformat()
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == [dict(
        person_id=m['id'], title='New on Ahavah: quick questions',
        body='Mountains or the sea? Answer with one tap.',
        url='/discover?src=lpush', tag=f'question:{live_on}')]
    assert _logs(m) == {('questions_launch', 'launch'), ('question', live_on)}
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert len(_to(pushed_questions, m)) == 1


def test_the_launch_push_spends_the_weeks_budget(push_member, pushed_questions, week, launch_on):
    from service.cron import returnmail
    m = push_member('LaunchBudget')
    _run(qp.queue_launch_pushes, _evening(week['today']))
    _run(qp.queue_weekly_question_pushes, _evening(week['today']))
    assert [p['title'] for p in _to(pushed_questions, m)] == ['New on Ahavah: quick questions']
    names = [name for name, _ in returnmail.JOBS]
    assert names.index('questions_launch_push') < names.index('question_push')


def test_it_reaches_members_who_answered_or_have_been_away(push_member, pushed_questions, week, launch_on):
    answered = push_member('LaunchAnswered')
    away = push_member('LaunchAway', online_days_ago=90)
    q = week['question']
    with api_tx() as tx:
        tx.execute("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
                   dict(p=answered['id'], k=q['key'], c=q['options'][0]['key']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert len(_to(pushed_questions, answered)) == len(_to(pushed_questions, away)) == 1


def test_never_to_a_member_who_left_campaign_emails(push_member, pushed_questions, week, launch_on):
    m = push_member('LaunchLeft')
    with api_tx() as tx:
        tx.execute('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', dict(p=m['id']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []


def test_once_ever(push_member, pushed_questions, week, launch_on):
    m = push_member('LaunchTwice')
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'launch', NOW() - interval '30 days')""",
                   dict(p=m['id']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []
