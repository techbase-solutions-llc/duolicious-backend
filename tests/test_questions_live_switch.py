"""The master switch: quick questions stay dark until launch (TEC-1845).

AHAVAH_QUESTIONS_LIVE_ENABLED, off by default, so the web screens can deploy
before launch day. While it is off a member gets no card, no catch-up, no
Quick answers on a profile, no match question (and none is assigned), and
an answer is refused as a closed question is, so a stale page cannot save.
Every question push, the E2 line and the launch email send nothing even
with their own switches on. Admin > Questions keeps working, so the owner
can approve the schedule beforehand, and the proofs still reach the owner.
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from database import api_tx
from service.campaigns import held
from service.questions import pushes as qp
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc
LIVE_ENV = 'AHAVAH_QUESTIONS_LIVE_ENABLED'


@pytest.fixture
def dark(monkeypatch):
    """The master switch off, every other question switch on: what is left
    dark is the master switch's doing."""
    monkeypatch.delenv(LIVE_ENV, raising=False)
    for env in ('AHAVAH_QUESTION_PUSH_ENABLED', 'AHAVAH_MATCH_QUESTION_PUSH_ENABLED',
                'AHAVAH_E2_QUESTION_LINE_ENABLED', 'AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED',
                'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED'):
        monkeypatch.setenv(env, '1')


@pytest.fixture
def week(make_question, drops):
    q = make_question(labels=('Mountains', 'The sea'))
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _member(make_person, sign_in, name: str) -> dict:
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def _match(a, b, hours_ago: int = 0) -> str:
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        return str(tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
               VALUES (%(a)s, %(b)s, NOW() - make_interval(hours => %(h)s)) RETURNING match_id""",
            dict(a=lo, b=hi, h=hours_ago)).fetchone()['match_id'])


def _run(job, now) -> None:
    with api_tx() as tx:
        job(tx, now)
    held.run_after_commit()


def _evening(day) -> datetime:
    return datetime.combine(day, time(18, 30), ZoneInfo('UTC')).astimezone(UTC)


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------

def test_the_master_switch_is_off_unless_set(monkeypatch):
    from service.campaigns.switches import SWITCHES, enabled
    from service.questions import live
    assert SWITCHES['questions_live'] == LIVE_ENV
    monkeypatch.delenv(LIVE_ENV, raising=False)
    assert enabled('questions_live') is False and live() is False
    monkeypatch.setenv(LIVE_ENV, '1')
    assert live() is True


def test_every_question_send_switch_needs_the_master_switch(dark, monkeypatch):
    from service.questions import switch_on
    names = ('question_push', 'match_question_push', 'e2_question_line',
             'questions_launch_email', 'questions_launch_push')
    assert not [n for n in names if switch_on(n)]
    monkeypatch.setenv(LIVE_ENV, '1')
    assert all(switch_on(n) for n in names)


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------

def test_no_card_while_dark(client, make_person, sign_in, week, dark):
    me = _member(make_person, sign_in, 'DarkCard')
    r = client.get('/questions/current', headers=me['headers'])
    assert r.status_code == 200 and r.get_json() == dict(current=None)


def test_no_catch_up_while_dark(client, make_person, sign_in, make_question, dark):
    make_question()
    me = _member(make_person, sign_in, 'DarkCatch')
    r = client.get('/questions/catch-up', headers=me['headers'])
    assert r.status_code == 200 and r.get_json() == dict(declined=False, questions=[])


def test_an_answer_is_refused_while_dark(client, make_person, sign_in, make_question, dark):
    q = make_question()
    me = _member(make_person, sign_in, 'DarkAnswer')
    for keep in (False, True):
        r = client.put(f"/answers/{q['key']}", headers=me['headers'],
                       json=dict(choice_key=q['options'][0]['key'], keep_existing=keep))
        assert r.status_code == 404 and r.get_json() == dict(error='closed')
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM prompt_answer WHERE person_id = %(p)s',
                          dict(p=me['id'])).fetchone() is None


def test_no_match_question_while_dark_and_none_assigned(client, make_person, sign_in, make_question, dark):
    make_question()
    a, b = _member(make_person, sign_in, 'DarkCtxA'), _member(make_person, sign_in, 'DarkCtxB')
    match_id = _match(a, b)
    r = client.get(f"/conversation-context/{b['uuid']}", headers=a['headers'])
    assert r.status_code == 200 and r.get_json() == dict(match_question=None)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM match_question WHERE match_id = %(m)s::uuid',
                          dict(m=match_id)).fetchone() is None


def test_still_no_context_without_a_match_while_dark(client, make_person, sign_in, dark):
    a, b = _member(make_person, sign_in, 'DarkNoA'), _member(make_person, sign_in, 'DarkNoB')
    assert client.get(f"/conversation-context/{b['uuid']}", headers=a['headers']).status_code == 404


def test_no_quick_answers_on_a_profile_while_dark(make_question, make_person, dark):
    from service.questions.member import quick_answers_for
    q = make_question()
    viewer, other = make_person(name='DarkViewer'), make_person(name='DarkOther')
    with api_tx() as tx:
        for p in (viewer, other):
            tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                          VALUES (%(p)s, %(k)s, %(c)s)""",
                       dict(p=p['id'], k=q['key'], c=q['options'][0]['key']))
    with api_tx('read committed') as tx:
        assert quick_answers_for(tx, viewer['id'], other['id']) == []


def test_the_prospect_profile_carries_an_empty_quick_answers_while_dark(client, make_person, add_photo,
                                                                        sign_in, make_question, dark):
    q = make_question()
    viewer, other = make_person(name='DarkPV', gender='Man'), make_person(name='DarkPO', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = TRUE, country = 'XQ',
                      show_my_location = TRUE, last_online_time = NOW(),
                      ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || %(x)s::jsonb
                WHERE id = ANY(%(i)s)""",
            dict(x=json.dumps(dict(citySet=True)), i=[viewer['id'], other['id']]))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) VALUES (%(i)s, 'XQ')",
                   dict(i=viewer['id']))
        for p in (viewer, other):
            tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                          VALUES (%(p)s, %(k)s, %(c)s)""",
                       dict(p=p['id'], k=q['key'], c=q['options'][0]['key']))
    add_photo(other['id'], position=1, face_count=1)
    r = client.get(f"/prospect-profile/{other['uuid']}", headers=sign_in(viewer))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['quick_answers'] == []


# ---------------------------------------------------------------------------
# Pushes, E2 and the launch email
# ---------------------------------------------------------------------------

def test_no_question_push_of_any_kind_while_dark(push_member, pushed_questions, week, dark):
    a, b = push_member('DarkPushA'), push_member('DarkPushB')
    _match(a, b, 25)
    for job in (qp.queue_match_question_pushes, qp.queue_launch_pushes, qp.queue_weekly_question_pushes):
        _run(job, _evening(week['today']))
    assert [p for p in pushed_questions if p['person_id'] in (a['id'], b['id'])] == []
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM push_send_log WHERE person_id = ANY(%(p)s)',
                          dict(p=[a['id'], b['id']])).fetchone() is None


def test_no_e2_question_line_while_dark(make_person, make_question, drops, dark):
    from emails import send_community_weekly as e2
    q = make_question(labels=('The window seat', 'The aisle seat'), text='Window seat or aisle?')
    drops(barbados_today() - timedelta(days=1), q['key'])
    p = make_person(name='DarkE2', email=f'darke2-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    _, html = e2.build_for(dict(person_id=p['id'], email=email, name='x',
                                week=dict(new_members=[], total=40, spotlight=None)))
    assert "This week's question" not in html


def test_no_launch_email_while_dark(make_person, week, dark):
    from emails import questions_launch as ql
    p = make_person(name='DarkLaunch', email=f'darklaunch-{uuid4().hex[:8]}@ahavah-test.invalid')
    _run(ql.queue_due, datetime.combine(week['today'], time(12, 30), UTC))
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'questions_launch'",
                          dict(p=p['id'])).fetchone() is None


# ---------------------------------------------------------------------------
# What stays on
# ---------------------------------------------------------------------------

def test_admin_questions_work_while_dark(client, make_person, dark):
    import hashlib
    import secrets
    tok, person = secrets.token_hex(32), make_person(name='DarkAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=person['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=person['id']))
    admin = {'Authorization': f'Bearer {tok}'}
    body = client.get('/admin/questions', headers=admin).get_json()
    assert body['switches']['questions_live'] is False
    assert len(client.get('/admin/questions/schedule', headers=admin).get_json()['weeks']) == 6
    assert isinstance(client.get('/admin/questions/pushes', headers=admin).get_json()['weeks'], list)


def test_the_proofs_still_reach_the_owner_while_dark(monkeypatch, dark):
    from scripts import send_question_proofs as sq
    sent, pushes = [], []

    class _Smtp:
        def send(self, **kw):
            sent.append(kw)
            return 'proof-id'

    monkeypatch.setattr(sq, '_smtp', lambda: _Smtp())
    monkeypatch.setattr(sq, '_subscriptions', lambda pid: [dict(endpoint='https://push.test/a', p256dh='k', auth='a')])
    monkeypatch.setattr(sq, '_push_one', lambda sub, payload: pushes.append(payload))
    sq.main(['--send'])
    assert {s['to_addr'] for s in sent} == {sq.PROOF_TO} and len(sent) == 2
    assert "This week's question" in sent[0]['body']
    assert sent[1]['subject'] == '[PROOF] New on Ahavah: quick questions'
    assert len(pushes) == 3
