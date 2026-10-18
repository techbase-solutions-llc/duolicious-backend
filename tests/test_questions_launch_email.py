"""The launch email (TEC-1845, spec "Launch").

To every member who has not left campaign emails, once per member ever, on
a drop day from 12:00 UTC while its switch is on. One button per option,
each its own campaign link to /q/{key}/{choice}; the click alone saves
nothing (the web page saves once the member is signed in). Exempt from the
7-day campaign cap, which E2 would otherwise trip for nearly everyone.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import questions_launch as ql
from service.campaigns import SELF_CAPPED_CAMPAIGNS
from service.config import WEB_BASE_URL
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc


@pytest.fixture
def on(monkeypatch, questions_live):
    """Its own switch and the questions_live master switch, both on."""
    monkeypatch.setenv('AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    q = make_question(labels=('Mountains', 'The sea'),
                      text='Would you rather wake up to mountains or the sea?')
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _at(day, hour, minute=30) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def _member(make_person, name):
    return make_person(name=name, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')


def _run(now) -> None:
    with api_tx() as tx:
        ql.queue_due(tx, now)


def _queued(person) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, exempt, unsub_scope, payload->>'subject' AS subject,
                      payload->>'html' AS html
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'questions_launch'""",
            dict(p=person['id'])).fetchall()]


def test_off_by_default(make_person, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED', raising=False)
    m = _member(make_person, 'LaunchMailOff')
    _run(_at(week['today'], 12))
    assert _queued(m) == []


def test_its_own_switch_alone_sends_nothing(make_person, week, monkeypatch):
    """Both switches: its own, and questions_live (service.questions.switch_on)."""
    monkeypatch.setenv('AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_QUESTIONS_LIVE_ENABLED', raising=False)
    m = _member(make_person, 'LaunchMailDark')
    _run(_at(week['today'], 12))
    assert _queued(m) == []


def test_on_a_drop_day_from_12_utc_each_member_gets_it_once(make_person, week, on):
    m = _member(make_person, 'LaunchMail')
    _run(_at(week['today'], 12))
    [row] = _queued(m)
    assert (row['campaign_id'], row['exempt'], row['unsub_scope'], row['subject']) == (
        'questions_launch', True, 'campaigns', 'New on Ahavah: quick questions')
    with api_tx('read committed') as tx:
        targets = {r['target_url'] for r in tx.execute(
            "SELECT target_url FROM campaign_link WHERE kind = 'questions_launch' AND subject_person_id = %(p)s",
            dict(p=m['id'])).fetchall()}
    q = week['question']
    assert targets == {f"{WEB_BASE_URL.rstrip('/')}/q/{q['key']}/{o['key']}" for o in q['options']}
    _run(_at(week['today'], 15))
    assert len(_queued(m)) == 1


def test_not_before_12_or_on_a_day_without_a_drop(make_person, week, on):
    m = _member(make_person, 'LaunchMailEarly')
    _run(_at(week['today'], 11))
    _run(_at(week['today'] + timedelta(days=1), 12))
    assert _queued(m) == []


def test_never_twice(make_person, week, on):
    m = _member(make_person, 'LaunchMailTwice')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'questions_launch', NOW() - interval '20 days')""",
                   dict(p=m['id']))
    _run(_at(week['today'], 12))
    assert _queued(m) == []


def test_not_to_a_member_who_left_campaign_emails_or_to_staff(make_person, week, on):
    left, staff = _member(make_person, 'LaunchMailLeft'), _member(make_person, 'LaunchMailStaff')
    with api_tx() as tx:
        tx.execute('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', dict(p=left['id']))
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(p)s", dict(p=staff['id']))
    _run(_at(week['today'], 12))
    assert _queued(left) == _queued(staff) == []


def test_the_email_reads_as_drafted():
    subject, html = ql.preview('owner@example.org')
    assert subject == 'New on Ahavah: quick questions'
    for text in ('New in the app', 'alt="Quick questions."',
                 'Each week a light question now waits for you in the app.',
                 'This week: would you rather wake up to mountains or the sea?',
                 '>Mountains<', '>The sea<',
                 "Tap your answer. We'll save it once you're signed in.",
                 'Also new on Ahavah',
                 'See who liked you in Liked you, and like them back from their profile.',
                 'Discover now keeps going past the first 10 profiles.',
                 'A reminder when a match or a message is waiting for you.',
                 "This week's is mountains or the sea. Tap your answer."):
        assert text in html, text
    assert '\u2014' not in html and 'Sunday' not in html


def test_it_is_exempt_from_the_7_day_cap():
    assert 'questions_launch' in SELF_CAPPED_CAMPAIGNS


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = [tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                  for t in ('campaign_link', 'email_outbox')]
    ql.preview('owner@example.org')
    with api_tx('read committed') as tx:
        after = [tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                 for t in ('campaign_link', 'email_outbox')]
    assert after == before
