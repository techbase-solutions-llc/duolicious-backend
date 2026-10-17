"""The silent-match push and the weekly question push (TEC-1845, spec
"Notifications").

Both share 1 push per member per question week; the silent-match push runs
first and wins. Weekly: 18:00 to 21:00 the member's local time on the drop
day, to members active in 60 days who have not answered, held by the gap.
Silent match: from 24 hours after a match with no message, once per match,
to both members, outside quiet hours, not held by the gap. Neither goes in
a rest period, to anyone who left campaign emails, to staff or after 2
pushes with no visit.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from emails import reminders as rm
from service.campaigns import held
from service.questions import copy
from service.questions import pushes as qp
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_QUESTION_PUSH_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MATCH_QUESTION_PUSH_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    """This week's question goes live today (Barbados date)."""
    q = make_question(labels=('Mountains', 'The sea'))
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _at(day, hour, minute=30, tz='UTC') -> datetime:
    return datetime.combine(day, time(hour, minute), ZoneInfo(tz)).astimezone(UTC)


def _run(job, now) -> None:
    with api_tx() as tx:
        job(tx, now)
    held.run_after_commit()


def _to(sent, person) -> list[dict]:
    return [p for p in sent if p['person_id'] == person['id']]


def _match(a, b, hours_ago) -> str:
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        return str(tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
               VALUES (%(a)s, %(b)s, NOW() - make_interval(hours => %(h)s)) RETURNING match_id""",
            dict(a=lo, b=hi, h=hours_ago)).fetchone()['match_id'])


def _sql(query, **params) -> None:
    with api_tx() as tx:
        tx.execute(query, params)


def _likes_waiting_queued_now(person) -> None:
    _sql("""INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload, unsub_scope)
            SELECT 'likes_waiting', 'gap-test', id, email, '{}'::jsonb, 'campaigns'
              FROM person WHERE id = %(p)s""", p=person['id'])


def test_nothing_goes_while_the_switches_are_off(push_member, pushed_questions, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTION_PUSH_ENABLED', raising=False)
    monkeypatch.delenv('AHAVAH_MATCH_QUESTION_PUSH_ENABLED', raising=False)
    a, b = push_member('OffA'), push_member('OffB')
    _match(a, b, 25)
    _run(qp.queue_match_question_pushes, _at(week['today'], 18))
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, a) == _to(pushed_questions, b) == []


def test_the_weekly_question_goes_at_18_local_on_the_drop_day(push_member, pushed_questions, week, on):
    m = push_member('Weekly')
    live_on = week['today'].isoformat()
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == [dict(
        person_id=m['id'], title="This week's question",
        body='Mountains or the sea? One tap, then see who picked the same.',
        url='/discover?src=qpush', tag=f'question:{live_on}')]
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = 'question' "
                          "AND campaign_id = %(w)s", dict(p=m['id'], w=live_on)).fetchone()
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 19))
    assert len(_to(pushed_questions, m)) == 1


def test_not_before_18_or_from_21_or_on_another_day(push_member, pushed_questions, week, on):
    m = push_member('Window')
    for now in (_at(week['today'], 17), _at(week['today'], 21),
                _at(week['today'] + timedelta(days=1), 18)):
        _run(qp.queue_weekly_question_pushes, now)
    assert _to(pushed_questions, m) == []


def test_the_members_own_time_zone_sets_the_hour(push_member, pushed_questions, week, on):
    m = push_member('Chicago', tz='America/Chicago')
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == [], '18:30 UTC is the early afternoon in Chicago'
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18, tz='America/Chicago'))
    assert len(_to(pushed_questions, m)) == 1


def test_a_member_with_no_time_zone_is_pushed_at_18_eastern(push_member, pushed_questions, week, on):
    m = push_member('NoZone', tz=None)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18, tz='America/New_York'))
    assert len(_to(pushed_questions, m)) == 1


def test_who_is_left_out(push_member, pushed_questions, week, on):
    control = push_member('Control')
    answered, away, off = push_member('Answered'), push_member('Away', online_days_ago=61), push_member('Off')
    left, nosub, staff = push_member('Left'), push_member('NoSub', push=False), push_member('Staff')
    q = week['question']
    _sql("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
         p=answered['id'], k=q['key'], c=q['options'][0]['key'])
    _sql('INSERT INTO notification_preference (person_id, push_questions) VALUES (%(p)s, FALSE)', p=off['id'])
    _sql('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', p=left['id'])
    _sql("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(p)s", p=staff['id'])
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    got = {p['person_id'] for p in pushed_questions}
    assert control['id'] in got
    assert not got & {answered['id'], away['id'], off['id'], left['id'], nosub['id'], staff['id']}


def test_nothing_goes_in_a_rest_period(push_member, pushed_questions, week, on, monkeypatch):
    a, b = push_member('RestA'), push_member('RestB')
    _match(a, b, 25)
    monkeypatch.setattr(rd, 'REST_DAYS', (week['today'],))
    _run(qp.queue_match_question_pushes, _at(week['today'], 18))
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, a) == _to(pushed_questions, b) == []


def test_the_gap_holds_the_weekly_push(push_member, pushed_questions, week, on):
    m = push_member('Gap')
    _likes_waiting_queued_now(m)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []


def test_pushes_stop_after_2_with_no_visit(push_member, pushed_questions, week, on):
    m = push_member('Unvisited', online_days_ago=10)
    for days, cid in ((8, '2000-01-02'), (6, '2000-01-09')):
        _sql("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                VALUES (%(p)s, 'question', %(c)s, NOW() - make_interval(days => %(d)s))""",
             p=m['id'], c=cid, d=days)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []
    _sql('UPDATE person SET last_online_time = NOW() WHERE id = %(p)s', p=m['id'])
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 19))
    assert len(_to(pushed_questions, m)) == 1


def test_a_silent_match_gets_one_push_each_after_24_hours(push_member, pushed_questions, on):
    a, b = push_member('SilentA', gender='Man'), push_member('SilentB')
    mid = _match(a, b, 25)
    now = _at(barbados_today(), 12)
    _run(qp.queue_match_question_pushes, now)
    assert _to(pushed_questions, a) == [dict(
        person_id=a['id'], title='An easy first line',
        body='Your new match has a question waiting. Answer first, then see theirs.',
        url=f"/chat/{b['uuid']}?src=mpush", tag=f'match:{mid}')]
    assert [p['url'] for p in _to(pushed_questions, b)] == [f"/chat/{a['uuid']}?src=mpush"]
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM match_question WHERE match_id = %(m)s::uuid', dict(m=mid)).fetchone()
    _run(qp.queue_match_question_pushes, now + timedelta(hours=1))
    assert len(_to(pushed_questions, a)) == 1


def test_not_before_24_hours_or_once_anyone_has_written(push_member, pushed_questions, on):
    a, b = push_member('EarlyA'), push_member('EarlyB')
    _match(a, b, 23)
    c, d = push_member('WroteC'), push_member('WroteD')
    _match(c, d, 25)
    _sql('INSERT INTO messaged (subject_person_id, object_person_id) VALUES (%(s)s, %(o)s)', s=d['id'], o=c['id'])
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert not [p for p in pushed_questions if p['person_id'] in {a['id'], b['id'], c['id'], d['id']}]


def test_a_silent_match_push_waits_out_quiet_hours(push_member, pushed_questions, on):
    a, b = push_member('QuietA'), push_member('QuietB')
    _match(a, b, 30)
    day = barbados_today()
    _run(qp.queue_match_question_pushes, _at(day, 22))
    _run(qp.queue_match_question_pushes, _at(day + timedelta(days=1), 7))
    assert _to(pushed_questions, a) == []
    _run(qp.queue_match_question_pushes, _at(day + timedelta(days=1), 8))
    assert len(_to(pushed_questions, a)) == 1


def test_the_silent_match_push_comes_first_and_spends_the_week(push_member, pushed_questions, week, on):
    from service.cron import returnmail
    a, b = push_member('FirstA'), push_member('FirstB')
    _match(a, b, 25)
    now = _at(week['today'], 18)
    _run(qp.queue_match_question_pushes, now)
    _run(qp.queue_weekly_question_pushes, now)
    assert [p['title'] for p in _to(pushed_questions, a)] == ['An easy first line']
    names = [name for name, _ in returnmail.JOBS]
    assert names.index('match_question_push') < names.index('question_push')


def test_the_silent_match_push_is_not_held_by_the_gap(push_member, pushed_questions, on):
    a, b = push_member('UnheldA'), push_member('UnheldB')
    _match(a, b, 25)
    _likes_waiting_queued_now(a)
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert len(_to(pushed_questions, a)) == 1


def test_no_silent_match_push_when_the_other_member_is_deactivated(push_member, pushed_questions, on):
    a, b = push_member('GoneA'), push_member('GoneB')
    _match(a, b, 25)
    _sql('UPDATE person SET activated = FALSE WHERE id = %(p)s', p=b['id'])
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert _to(pushed_questions, a) == []


def test_a_match_gets_the_question_push_and_the_3_day_reminder(push_member, pushed_questions, on, monkeypatch):
    # The spec lets both go: they say different things.
    monkeypatch.setenv('AHAVAH_MATCH_REMINDER_ENABLED', '1')
    reminded: list[int] = []
    monkeypatch.setattr(rm, '_push', lambda person_id, title, body, url, kind: reminded.append(person_id))
    monkeypatch.setattr(rm, 'PUSH_READY', lambda: True)
    a, b = push_member('BothA', online_days_ago=2), push_member('BothB', online_days_ago=2)
    _match(a, b, 73)
    tuesday = datetime(2026, 10, 13, 13, tzinfo=UTC)
    _run(qp.queue_match_question_pushes, tuesday)
    _run(rm.queue_match_reminders, tuesday)
    assert len(_to(pushed_questions, a)) == 1 and a['id'] in reminded


def test_a_push_that_fails_is_tried_again(push_member, on, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('push service down')
    monkeypatch.setattr(qp, '_push', boom)
    monkeypatch.setattr(qp, 'PUSH_READY', lambda: True)
    a, b = push_member('FlakyA'), push_member('FlakyB')
    _match(a, b, 25)
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = 'match_question'",
                          dict(p=a['id'])).fetchone() is None


def test_every_push_fits_a_lock_screen():
    with api_tx('read committed') as tx:
        rows = tx.execute("""SELECT key, text, format, options FROM prompt_bank
                              WHERE active AND format IN ('either_or', 'pick_one')""").fetchall()
    assert rows
    for r in rows:
        for push in (copy.weekly_push('2026-11-15', dict(r)), copy.launch_push('2026-11-15', dict(r))):
            assert len(push['body']) <= copy.LOCK_SCREEN_CHARS, push['body']
    assert len(copy.MATCH_BODY) <= copy.LOCK_SCREEN_CHARS
