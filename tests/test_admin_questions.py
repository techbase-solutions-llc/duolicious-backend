"""Admin > Questions, the API (TEC-1845, spec "Screens" 7).

The bank with its options and counts split by sex (counts only); switching
a question on or off and editing option wording, never its keys; the next
6 weeks with the approved order proposed for empty weeks, which the owner
fills, reorders and approves; pushes sent, tapped and switched off by week,
with the guard rail at 2 switch-offs; and the state of each switch.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.questions import admin as qa
from service.questions.schedule import FIRST_WEEKS

pytestmark = pytest.mark.usefixtures('questions_schema')

SUN = date(2027, 1, 3)
NOW = datetime.combine(SUN - timedelta(days=2), time(15), timezone.utc)  # Friday 1 Jan 2027


def _headers(person, admin: bool) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=person['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=person['id']))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2027, 12, 31))
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    window = dict(a=SUN - timedelta(days=7), b=SUN + timedelta(days=70))
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)
    yield
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)


def _answer(person_id, question, index):
    with api_tx() as tx:
        tx.execute("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
                   dict(p=person_id, k=question['key'], c=question['options'][index]['key']))


def test_only_an_admin_may_read_or_change(client, make_person, make_question):
    member = _headers(make_person(name='QaMember'), admin=False)
    q = make_question()
    assert client.get('/admin/questions', headers=member).status_code == 403
    assert client.get('/admin/questions/schedule', headers=member).status_code == 403
    assert client.patch(f"/admin/questions/{q['key']}", headers=member, json=dict(active=False)).status_code == 403


def test_the_bank_lists_every_question_with_its_split_by_sex(client, make_person, make_question):
    admin = _headers(make_person(name='QaAdmin'), admin=True)
    q = make_question()
    for name, gender, index in (('QaW1', 'Woman', 0), ('QaW2', 'Woman', 0), ('QaM1', 'Man', 1)):
        _answer(make_person(name=name, gender=gender)['id'], q, index)
    body = client.get('/admin/questions', headers=admin).get_json()
    rows = {r['key']: r for r in body['bank']}
    assert {'mountains-or-sea', 'pet'} <= set(rows)
    row = rows[q['key']]
    assert row['answers'] == 3
    assert [(o['n'], o['by_sex']) for o in row['options']] == [(2, {'woman': 2}), (1, {'man': 1})]
    assert set(body['switches']) == set(qa.SWITCH_NAMES)


def test_a_label_edit_keeps_every_answer(client, make_person, make_question):
    admin = _headers(make_person(name='QaLabel'), admin=True)
    q = make_question(labels=('Mountains', 'The sea'))
    member = make_person(name='QaLabelMember')
    _answer(member['id'], q, 0)
    first = q['options'][0]['key']
    r = client.patch(f"/admin/questions/{q['key']}", headers=admin, json=dict(labels={first: 'The hills'}))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [o['label'] for o in r.get_json()['options']] == ['The hills', 'The sea']
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT choice_key FROM prompt_answer WHERE person_id = %(p)s AND prompt_key = %(k)s',
                          dict(p=member['id'], k=q['key'])).fetchone()['choice_key'] == first


def test_a_bad_label_or_switching_on_an_open_question_is_refused(client, make_person, make_question):
    admin = _headers(make_person(name='QaBad'), admin=True)
    q = make_question()
    first = q['options'][0]['key']
    for labels in ({first: 'x' * 41}, {'not-an-option': 'X'}, {first: 'A \u2014 B'}, {first: '  '}, {}):
        r = client.patch(f"/admin/questions/{q['key']}", headers=admin, json=dict(labels=labels))
        assert (r.status_code, r.get_json()) == (400, dict(error='bad_labels')), labels
    r = client.patch('/admin/questions/pet', headers=admin, json=dict(active=True))
    assert (r.status_code, r.get_json()) == (400, dict(error='not_a_choice_question'))
    assert client.patch('/admin/questions/no-such-question', headers=admin,
                        json=dict(active=False)).status_code == 404


def test_the_schedule_shows_6_weeks_with_the_approved_order_proposed(calendar):
    with api_tx('read committed') as tx:
        rows = qa.schedule_rows(tx, NOW)
        used = {r['prompt_key'] for r in tx.execute('SELECT DISTINCT prompt_key FROM question_drop').fetchall()}
    assert [r['week_of'] for r in rows] == [(SUN - timedelta(days=7) + timedelta(weeks=i)).isoformat() for i in range(6)]
    assert [r['live_on'] for r in rows] == [r['week_of'] for r in rows], 'with no rest day, each drop is the Sunday'
    assert rows[0]['proposed_key'] is None, 'a week already under way is not proposed'
    fresh = [k for k in FIRST_WEEKS if k not in used]
    k = min(5, len(fresh))
    assert [r['proposed_key'] for r in rows[1:1 + k]] == fresh[:k]


def test_a_week_can_be_filled_reordered_and_approved(calendar, make_question):
    q1, q2 = make_question(), make_question()
    week2 = SUN + timedelta(days=7)
    with api_tx() as tx:
        qa.set_drop(tx, SUN, q1['key'], now=NOW)
        assert qa.approve(tx, [SUN, week2], now=NOW) == [SUN.isoformat(), week2.isoformat()]
        rows = {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}
        assert (rows[SUN.isoformat()]['prompt_key'], rows[SUN.isoformat()]['approved']) == (q1['key'], True)
        assert rows[week2.isoformat()]['approved'] is True and rows[week2.isoformat()]['prompt_key']
        qa.set_drop(tx, SUN, q2['key'], now=NOW)
        rows = {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}
        assert (rows[SUN.isoformat()]['prompt_key'], rows[SUN.isoformat()]['approved']) == (q2['key'], False)
        qa.clear_drop(tx, SUN, now=NOW)
        assert {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}[SUN.isoformat()]['prompt_key'] is None


def test_a_question_goes_only_on_its_weeks_drop_day(calendar, client, make_person, make_question):
    q, off = make_question(), make_question(active=False)
    cases = ((SUN + timedelta(days=1), q['key'], 'not_a_drop_day'),
             (SUN - timedelta(days=7), q['key'], 'already_live'),
             (SUN, off['key'], 'not_a_live_question'))
    for day, key, reason in cases:
        with pytest.raises(qa.ScheduleRefused, match=reason):
            with api_tx() as tx:
                qa.set_drop(tx, day, key, now=NOW)
    admin = _headers(make_person(name='QaDay'), admin=True)
    r = client.put('/admin/questions/schedule/not-a-date', headers=admin, json=dict(prompt_key=q['key']))
    assert (r.status_code, r.get_json()) == (400, dict(error='bad_day'))


def test_pushes_taps_and_switch_offs_by_week(calendar, make_person, make_question):
    q = make_question()
    a, b = make_person(name='QaPushA'), make_person(name='QaPushB')
    in_week = '2027-01-04 12:00:00+00'
    with api_tx() as tx:
        tx.execute("INSERT INTO question_drop (live_on, prompt_key, approved_at) VALUES (%(d)s, %(k)s, NOW())",
                   dict(d=SUN, k=q['key']))
        for p in (a, b):
            tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                          VALUES (%(p)s, 'question', '2027-01-03', %(t)s)""", dict(p=p['id'], t=in_week))
            tx.execute("""INSERT INTO notification_preference (person_id, push_questions, push_questions_off_at)
                          VALUES (%(p)s, FALSE, %(t)s)""", dict(p=p['id'], t=in_week))
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'launch', %(t)s)""", dict(p=a['id'], t=in_week))
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'match_question', 'm-qa', %(t)s)""", dict(p=b['id'], t=in_week))
        tx.execute("INSERT INTO push_tap (person_id, src, tapped_at) VALUES (%(p)s, 'qpush', %(t)s)",
                   dict(p=a['id'], t=in_week))
        rows = {r['live_on']: r for r in qa.push_rows(tx, weeks=52)}
    row = rows[SUN.isoformat()]
    assert (row['weekly_sent'], row['launch_sent'], row['match_question_sent']) == (1, 1, 1)
    assert row['taps'] == dict(qpush=1, mpush=0, lpush=0)
    assert (row['switched_off'], row['guard_rail']) == (2, True)


def test_switch_offs_count_members_only(calendar, make_person, make_question, monkeypatch):
    """Pushes go to members only, so a staff or test account turning them
    off while checking the setting is not a signal and must not trip the
    guard rail (TEC-1845 admin audit)."""
    q = make_question()
    member, staff, tester = (make_person(name='QaOffMember'), make_person(name='QaOffStaff'),
                             make_person(name='QaOffTester'))
    in_week = '2027-01-04 12:00:00+00'
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
        tester_email = tx.execute('SELECT lower(email) AS e FROM person WHERE id = %(i)s',
                                  dict(i=tester['id'])).fetchone()['e']
        tx.execute("INSERT INTO question_drop (live_on, prompt_key, approved_at) VALUES (%(d)s, %(k)s, NOW())",
                   dict(d=SUN, k=q['key']))
        for p in (member, staff, tester):
            tx.execute("""INSERT INTO notification_preference (person_id, push_questions, push_questions_off_at)
                          VALUES (%(p)s, FALSE, %(t)s)""", dict(p=p['id'], t=in_week))
    monkeypatch.setenv('AHAVAH_TEST_ACCOUNT_EMAILS', tester_email)
    with api_tx() as tx:
        row = {r['live_on']: r for r in qa.push_rows(tx, weeks=52)}[SUN.isoformat()]
    assert (row['switched_off'], row['guard_rail']) == (1, False)


def test_the_routes_answer_an_admin(client, make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTION_PUSH_ENABLED', raising=False)
    monkeypatch.setenv('AHAVAH_E2_QUESTION_LINE_ENABLED', '1')
    admin = _headers(make_person(name='QaRoutes'), admin=True)
    body = client.get('/admin/questions', headers=admin).get_json()
    assert body['switches']['e2_question_line'] is True and body['switches']['question_push'] is False
    assert len(client.get('/admin/questions/schedule', headers=admin).get_json()['weeks']) == 6
    assert isinstance(client.get('/admin/questions/pushes', headers=admin).get_json()['weeks'], list)
