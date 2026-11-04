"""Report rewards (report rewards plan, 3 Nov 2026, TEC-2025).

Rules locked in here:
  1. POST /feedback still takes anonymous reports, and stores the member
     when a signed-in member sends one. A bad token is treated as anonymous.
  2. Marking a report fixed pays 5 tokens (ledger reason report_reward) and
     30 days of Premium, once: a second attempt answers 409 and pays nothing.
  3. With no person_id, the member is the one account whose email matches
     the report's, ignoring case. No match: closed, no reward, no notice.
  4. A member with 3 rewarded reports in 30 days gets the notice only.
  5. reward=false writes the notice without paying; not a fault writes
     neither.
  6. A notice is visible to, and dismissable by, its member only.
  7. The send guard's daily reminder lists only reports still new after 24
     hours, with no message text and no address, once a day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

import smtp as smtp_mod
from database import api_tx
from service import sendguard
from service.feedback import insert as insert_feedback
from service.feedback import rewards

ADMIN_FIXED = '/admin/system/feedback/{}/fixed'
MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0091_report_rewards.sql'


@pytest.fixture(scope='module', autouse=True)
def _report_rewards_schema():
    """Apply 0091 again for this module: earlier modules (the token adjust
    tests) re-apply 0072, whose reason list lacks report_reward."""
    with api_tx() as tx:
        tx.execute(MIGRATION.read_text(encoding='utf-8'))

ADMIN_NOT_A_FAULT = '/admin/system/feedback/{}/not-a-fault'


@pytest.fixture
def feedback_rows():
    created: list[int] = []

    def _make(*, person_id=None, email=None, message='Messages show twice in a chat',
              category='problem', hours_old: int = 0) -> int:
        with api_tx() as tx:
            fid = insert_feedback(tx, category=category, message=message, email=email,
                                  path='/chat', user_agent='pytest', person_id=person_id)
            if hours_old:
                tx.execute("UPDATE feedback SET created_at = NOW() - make_interval(hours => %(h)s) "
                           "WHERE id = %(id)s", dict(h=hours_old, id=fid))
        created.append(fid)
        return fid

    yield _make

    with api_tx() as tx:
        for fid in created:
            tx.execute("DELETE FROM token_ledger WHERE reason = 'report_reward' "
                       "AND metadata->>'feedback_id' = %(f)s", dict(f=str(fid)))
            tx.execute('DELETE FROM member_notice WHERE feedback_id = %(f)s', dict(f=fid))
            tx.execute('DELETE FROM feedback WHERE id = %(f)s', dict(f=fid))


@pytest.fixture
def no_feedback_email(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr('service.api.feedback_routes.send_feedback_async', lambda **kw: sent.append(kw))
    return sent


def _feedback(fid: int) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM feedback WHERE id = %(i)s', dict(i=fid)).fetchone()


def _ledger(person_uuid: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return tx.execute(
            "SELECT delta, reason, metadata FROM token_ledger "
            "WHERE person_id = uuid_or_null(%(u)s) AND reason = 'report_reward' ORDER BY id",
            dict(u=person_uuid)).fetchall()


def _notices(person_id: int) -> list[dict]:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM member_notice WHERE person_id = %(p)s ORDER BY id',
                          dict(p=person_id)).fetchall()


def _email_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=person_id)).fetchone()['email']


# --- 1. capture -------------------------------------------------------------

def test_anonymous_feedback_is_still_accepted(client, no_feedback_email):
    r = client.post('/feedback', json=dict(category='problem', message='Anonymous report from pytest'))
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    with api_tx() as tx:
        row = tx.execute("SELECT id, person_id, status FROM feedback "
                         "WHERE message = 'Anonymous report from pytest' ORDER BY id DESC LIMIT 1").fetchone()
        tx.execute('DELETE FROM feedback WHERE id = %(i)s', dict(i=row['id']))
    assert row['person_id'] is None and row['status'] == 'new'
    assert len(no_feedback_email) == 1


def test_a_bad_token_is_treated_as_anonymous(client, no_feedback_email):
    r = client.post('/feedback', json=dict(category='idea', message='Bad token report from pytest'),
                    headers={'Authorization': 'Bearer not-a-real-token'})
    assert r.status_code == 200
    with api_tx() as tx:
        row = tx.execute("SELECT id, person_id FROM feedback "
                         "WHERE message = 'Bad token report from pytest' ORDER BY id DESC LIMIT 1").fetchone()
        tx.execute('DELETE FROM feedback WHERE id = %(i)s', dict(i=row['id']))
    assert row['person_id'] is None


def test_a_signed_in_member_is_stored_on_the_report(client, make_person, sign_in, no_feedback_email):
    p = make_person(name='Reporter')
    r = client.post('/feedback', json=dict(category='problem', message='Signed in report from pytest'),
                    headers=sign_in(p))
    assert r.status_code == 200
    with api_tx() as tx:
        row = tx.execute("SELECT id, person_id FROM feedback "
                         "WHERE message = 'Signed in report from pytest' ORDER BY id DESC LIMIT 1").fetchone()
        tx.execute('DELETE FROM feedback WHERE id = %(i)s', dict(i=row['id']))
    assert row['person_id'] == p['id']


# --- 2. paid once -----------------------------------------------------------

def test_fixed_pays_tokens_and_premium_and_writes_the_notice(client, admin_headers, make_person, feedback_rows):
    p = make_person(name='Paid')
    fid = feedback_rows(person_id=p['id'])
    before = datetime.now(timezone.utc)
    r = client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                    json=dict(notice_line='  We fixed the duplicate messages ', reward=True))
    assert r.status_code == 200, r.data
    out = r.get_json()
    assert out['outcome'] == 'paid' and out['paid'] is True and out['capped'] is False
    assert out['member'] == 'session' and out['reward_tokens'] == 5 and out['reward_days'] == 30

    ledger = _ledger(p['uuid'])
    assert [(l['delta'], l['reason']) for l in ledger] == [(5, 'report_reward')]
    assert ledger[0]['metadata']['feedback_id'] == str(fid)

    with api_tx('read committed') as tx:
        prem = tx.execute("SELECT 'premium' = ANY(entitlements) AS has, subscription_expires_at AS exp "
                          "FROM person WHERE id = %(i)s", dict(i=p['id'])).fetchone()
    assert prem['has'] is True
    assert abs((prem['exp'] - (before + timedelta(days=30))).total_seconds()) < 300

    fb = _feedback(fid)
    assert fb['status'] == 'fixed' and fb['handled_at'] is not None and fb['handled_by']
    assert (fb['reward_tokens'], fb['reward_days']) == (5, 30)
    assert fb['notice_line'] == 'We fixed the duplicate messages.'

    [n] = _notices(p['id'])
    assert n['kind'] == 'report_thanks' and n['title'] == 'Thanks for your report'
    assert n['body'] == 'We fixed the duplicate messages. You have 5 tokens and 30 more days of Premium.'
    assert (n['tokens'], n['premium_days'], n['feedback_id']) == (5, 30, fid)
    for text in (n['title'], n['body']):
        assert '—' not in text and '!' not in text


def test_a_second_fixed_answers_409_and_pays_nothing(client, admin_headers, make_person, feedback_rows):
    p = make_person(name='Twice')
    fid = feedback_rows(person_id=p['id'])
    body = dict(notice_line='We fixed it.', reward=True)
    assert client.post(ADMIN_FIXED.format(fid), headers=admin_headers, json=body).status_code == 200
    r = client.post(ADMIN_FIXED.format(fid), headers=admin_headers, json=body)
    assert r.status_code == 409 and r.get_json() == {'error': 'already_handled', 'status': 'fixed'}
    r = client.post(ADMIN_NOT_A_FAULT.format(fid), headers=admin_headers)
    assert r.status_code == 409
    assert len(_ledger(p['uuid'])) == 1 and len(_notices(p['id'])) == 1
    assert _feedback(fid)['status'] == 'fixed'


def test_the_service_refuses_a_handled_report_inside_one_transaction(make_person, feedback_rows):
    p = make_person(name='Service')
    fid = feedback_rows(person_id=p['id'])
    refused = None
    with api_tx('read committed') as tx:
        rewards.mark_fixed(tx, fid, notice_line='Fixed.', reward=True, handled_by='pytest')
        try:
            rewards.mark_fixed(tx, fid, notice_line='Fixed.', reward=True, handled_by='pytest')
        except rewards.AlreadyHandled as e:
            refused = e.status
    assert refused == 'fixed'
    assert len(_ledger(p['uuid'])) == 1


def test_the_member_notice_is_unique_per_report(make_person, feedback_rows):
    p = make_person(name='Unique')
    fid = feedback_rows(person_id=p['id'])
    with api_tx('read committed') as tx:
        rewards.mark_fixed(tx, fid, notice_line='Fixed.', reward=False, handled_by='pytest')
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO member_notice (person_id, kind, title, body, feedback_id) "
                       "VALUES (%(p)s, 'report_thanks', 't', 'b', %(f)s)", dict(p=p['id'], f=fid))


# --- 3. email fallback ------------------------------------------------------

def test_an_anonymous_report_reaches_the_member_by_email_ignoring_case(client, admin_headers, make_person,
                                                                       feedback_rows):
    p = make_person(name='ByEmail')
    fid = feedback_rows(email=_email_of(p['id']).upper())
    r = client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                    json=dict(notice_line='We fixed the photo upload.', reward=True))
    out = r.get_json()
    assert out['member'] == 'email' and out['outcome'] == 'paid'
    assert _feedback(fid)['person_id'] == p['id']
    assert len(_ledger(p['uuid'])) == 1 and len(_notices(p['id'])) == 1


def test_no_member_closes_with_no_reward_and_no_notice(client, admin_headers, feedback_rows):
    fid = feedback_rows(email='nobody-at-all@ahavah-test.invalid')
    r = client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                    json=dict(notice_line='Fixed.', reward=True))
    out = r.get_json()
    assert r.status_code == 200 and out['member'] == 'none' and out['outcome'] == 'member_none'
    assert out['notice_id'] is None and out['reward_tokens'] == 0
    fb = _feedback(fid)
    assert fb['status'] == 'fixed' and fb['person_id'] is None and fb['reward_tokens'] == 0
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM member_notice WHERE feedback_id = %(f)s',
                          dict(f=fid)).fetchone() is None


# --- 4. cap -----------------------------------------------------------------

def test_the_fourth_report_in_30_days_gets_the_notice_without_a_reward(client, admin_headers, make_person,
                                                                       feedback_rows):
    p = make_person(name='Capped')
    outcomes = []
    for i in range(4):
        fid = feedback_rows(person_id=p['id'], message=f'Cap report {i}')
        r = client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                        json=dict(notice_line=f'We fixed report {i}.', reward=True))
        outcomes.append((r.get_json()['outcome'], r.get_json()['capped']))
    assert outcomes == [('paid', False)] * 3 + [('capped', True)]
    assert sum(l['delta'] for l in _ledger(p['uuid'])) == 15
    notices = _notices(p['id'])
    assert len(notices) == 4
    assert notices[-1]['body'] == 'We fixed report 3.' and notices[-1]['tokens'] == 0


def test_a_reward_older_than_30_days_does_not_count_towards_the_cap(make_person, feedback_rows):
    p = make_person(name='Window')
    old = [feedback_rows(person_id=p['id'], message=f'Old report {i}') for i in range(3)]
    new = feedback_rows(person_id=p['id'], message='New report')
    with api_tx('read committed') as tx:
        for fid in old:
            rewards.mark_fixed(tx, fid, notice_line='Fixed.', reward=True, handled_by='pytest')
            tx.execute("UPDATE feedback SET handled_at = NOW() - interval '31 days' WHERE id = %(f)s",
                       dict(f=fid))
        assert rewards.rewarded_in_window(tx, p['id']) == 0
        assert rewards.mark_fixed(tx, new, notice_line='Fixed.', reward=True,
                                  handled_by='pytest')['outcome'] == 'paid'


# --- 5. no reward, not a fault ----------------------------------------------

def test_reward_false_writes_the_notice_only(client, admin_headers, make_person, feedback_rows):
    p = make_person(name='NoReward')
    fid = feedback_rows(person_id=p['id'])
    out = client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                      json=dict(notice_line='Thanks, that is fixed now', reward=False)).get_json()
    assert out['outcome'] == 'no_reward' and out['reward_tokens'] == 0
    assert _ledger(p['uuid']) == []
    [n] = _notices(p['id'])
    assert n['body'] == 'Thanks, that is fixed now.'


def test_not_a_fault_closes_with_no_reward_and_no_notice(client, admin_headers, make_person, feedback_rows):
    p = make_person(name='NotAFault')
    fid = feedback_rows(person_id=p['id'])
    r = client.post(ADMIN_NOT_A_FAULT.format(fid), headers=admin_headers)
    assert r.status_code == 200 and r.get_json()['status'] == 'not_a_fault'
    fb = _feedback(fid)
    assert fb['status'] == 'not_a_fault' and fb['handled_at'] is not None and fb['reward_tokens'] == 0
    assert _ledger(p['uuid']) == [] and _notices(p['id']) == []


def test_the_notice_line_is_required_and_held_to_200_characters(client, admin_headers, feedback_rows):
    fid = feedback_rows()
    assert client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                       json=dict(notice_line='   ', reward=True)).status_code == 400
    assert client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                       json=dict(notice_line='x' * 201, reward=True)).status_code == 400
    assert client.post(ADMIN_FIXED.format(fid), headers=admin_headers,
                       json=dict(reward=True)).status_code == 400
    assert _feedback(fid)['status'] == 'new'


def test_admin_routes_need_an_admin(client, make_person, sign_in, feedback_rows):
    member = sign_in(make_person(name='NotAdmin'))
    fid = feedback_rows()
    assert client.get('/admin/system/feedback', headers=member).status_code == 403
    assert client.post(ADMIN_FIXED.format(fid), headers=member,
                       json=dict(notice_line='x', reward=True)).status_code == 403
    assert client.post(ADMIN_NOT_A_FAULT.format(fid), headers=member).status_code == 403
    assert client.post(ADMIN_NOT_A_FAULT.format(999999999), headers=member).status_code == 403


def test_unknown_report_answers_404(client, admin_headers):
    assert client.post(ADMIN_NOT_A_FAULT.format(2_000_000_000), headers=admin_headers).status_code == 404
    assert client.post(ADMIN_FIXED.format(2_000_000_000), headers=admin_headers,
                       json=dict(notice_line='x', reward=True)).status_code == 404


def test_the_admin_list_filters_by_status_and_says_who_can_be_thanked(client, admin_headers, make_person,
                                                                      feedback_rows):
    p = make_person(name='Listed')
    linked = feedback_rows(person_id=p['id'], hours_old=5)
    anon = feedback_rows(email=None)
    closed = feedback_rows()
    client.post(ADMIN_NOT_A_FAULT.format(closed), headers=admin_headers)

    r = client.get('/admin/system/feedback?status=new', headers=admin_headers)
    assert r.status_code == 200
    body = r.get_json()
    rows = {f['id']: f for f in body['feedback']}
    assert linked in rows and anon in rows and closed not in rows
    assert rows[linked]['has_member'] is True and rows[anon]['has_member'] is False
    assert rows[linked]['age_hours'] >= 5 and rows[linked]['status'] == 'new'
    assert set(rows[linked]) >= {'id', 'category', 'message', 'email', 'path', 'created_at', 'status',
                                 'age_hours', 'has_member', 'reward_tokens', 'reward_days', 'handled_at'}
    assert set(body['counts']) == {'new', 'fixed', 'not_a_fault'}
    created = [f['created_at'] for f in body['feedback']]
    assert created == sorted(created, reverse=True)

    rows = {f['id'] for f in client.get('/admin/system/feedback?status=not_a_fault',
                                        headers=admin_headers).get_json()['feedback']}
    assert closed in rows and linked not in rows
    assert client.get('/admin/system/feedback?status=bogus', headers=admin_headers).status_code == 400


# --- 6. notices belong to their member --------------------------------------

def test_notices_are_visible_and_dismissable_by_their_member_only(client, make_person, sign_in, feedback_rows):
    owner = make_person(name='Owner')
    other = make_person(name='Other')
    owner_h, other_h = sign_in(owner), sign_in(other)
    fid = feedback_rows(person_id=owner['id'])
    with api_tx('read committed') as tx:
        out = rewards.mark_fixed(tx, fid, notice_line='We fixed it.', reward=True, handled_by='pytest')
    nid = out['notice_id']

    mine = client.get('/notices', headers=owner_h).get_json()['notices']
    assert [n['id'] for n in mine] == [nid]
    assert mine[0]['body'].startswith('We fixed it.') and mine[0]['seen_at'] is None
    assert client.get('/notices', headers=other_h).get_json() == {'notices': []}

    assert client.post(f'/notices/{nid}/dismiss', headers=other_h).status_code == 404
    assert client.post(f'/notices/{nid}/seen', headers=other_h).status_code == 404
    assert client.get('/notices').status_code in (400, 401)

    assert client.post(f'/notices/{nid}/seen', headers=owner_h).status_code == 200
    assert client.get('/notices', headers=owner_h).get_json()['notices'][0]['seen_at'] is not None
    assert client.post(f'/notices/{nid}/dismiss', headers=owner_h).status_code == 200
    assert client.get('/notices', headers=owner_h).get_json() == {'notices': []}
    [n] = _notices(owner['id'])
    assert n['seen_at'] is not None and n['dismissed_at'] is not None


def test_at_most_five_notices_newest_first(client, make_person, sign_in, feedback_rows):
    p = make_person(name='Many')
    fids = [feedback_rows(person_id=p['id'], message=f'Many {i}') for i in range(6)]
    for i, fid in enumerate(fids):
        with api_tx('read committed') as tx:
            rewards.mark_fixed(tx, fid, notice_line=f'Fixed {i}.', reward=False, handled_by='pytest')
    notices = client.get('/notices', headers=sign_in(p)).get_json()['notices']
    assert [n['body'] for n in notices] == [f'Fixed {i}.' for i in (5, 4, 3, 2, 1)]


# --- ledger reason ------------------------------------------------------------

def test_the_ledger_accepts_report_reward_and_still_refuses_an_unknown_reason(make_person):
    p = make_person(name='Ledger')
    with api_tx() as tx:
        tx.execute("INSERT INTO token_ledger (person_id, delta, reason, metadata) "
                   "VALUES (%(u)s::uuid, 1, 'report_reward', '{}'::jsonb)", dict(u=p['uuid']))
        tx.execute("DELETE FROM token_ledger WHERE person_id = %(u)s::uuid", dict(u=p['uuid']))
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO token_ledger (person_id, delta, reason, metadata) "
                       "VALUES (%(u)s::uuid, 1, 'not_a_reason', '{}'::jsonb)", dict(u=p['uuid']))


def test_the_migration_runs_twice():
    for _ in range(2):
        with api_tx() as tx:
            tx.execute(MIGRATION.read_text(encoding='utf-8'))


# --- 7. the owner's daily reminder --------------------------------------------

@pytest.fixture
def guard_mail(monkeypatch):
    with api_tx() as tx:
        tx.execute("DELETE FROM send_guard_event WHERE event = %(e)s", dict(e=sendguard.FEEDBACK_ALERT_EVENT))
    monkeypatch.setenv('AHAVAH_ALERT_EMAILS', 'owner@ahavah-test.invalid')
    out: list[dict] = []
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', lambda self, **kw: out.append(kw) or 'mid')
    monkeypatch.setattr('service.notifications._send_to_user_blocking', lambda *a, **kw: 1)
    monkeypatch.setattr(sendguard, 'FEEDBACK_ALERT_FROM_HOUR', 0)
    # The local test database keeps old reports from other runs; list them
    # all so this run's report is in the email.
    monkeypatch.setattr(sendguard, 'FEEDBACK_ALERT_LISTED', 100_000)
    yield out
    with api_tx() as tx:
        tx.execute("DELETE FROM send_guard_event WHERE event = %(e)s", dict(e=sendguard.FEEDBACK_ALERT_EVENT))


def test_the_reminder_lists_only_reports_still_new_after_24_hours(make_person, feedback_rows, guard_mail):
    secret = 'SECRET-MESSAGE-TEXT'
    stale = feedback_rows(email='stale-reporter@ahavah-test.invalid', message=secret, hours_old=30)
    fresh = feedback_rows(message=secret, hours_old=2)
    handled = feedback_rows(message=secret, hours_old=40)
    with api_tx('read committed') as tx:
        rewards.mark_not_a_fault(tx, handled, handled_by='pytest')
        [ev] = sendguard.unanswered_feedback_events(tx, from_hour=0)
    ids = [r['id'] for r in ev['detail']['reports']]
    assert stale in ids and fresh not in ids and handled not in ids
    mine = [r for r in ev['detail']['reports'] if r['id'] == stale][0]
    assert mine == dict(id=stale, category='problem', age_hours=30)

    sendguard.tick()
    [mail] = [m for m in guard_mail if f'report {stale} (problem, 30 hours)' in m['body']]
    assert secret not in mail['body'] and 'stale-reporter' not in mail['body'] and '@' not in mail['body']
    assert '—' not in mail['body'] and '!' not in mail['body']

    # Once a day: the next tick sends nothing more about reports.
    sent = len(guard_mail)
    sendguard.tick()
    assert len(guard_mail) == sent


def test_no_reminder_when_every_old_report_is_handled_or_before_the_hour(feedback_rows, guard_mail):
    with api_tx('read committed') as tx:
        old_new = tx.execute(
            "SELECT count(*) AS n FROM feedback WHERE status = 'new' "
            "AND created_at < NOW() - interval '24 hours'").fetchone()['n']
        assert sendguard.unanswered_feedback_events(tx, from_hour=25) == []
    if old_new == 0:
        with api_tx('read committed') as tx:
            assert sendguard.unanswered_feedback_events(tx, from_hour=0) == []


def test_the_reminder_lists_at_most_20_reports_and_counts_the_rest():
    reports = [dict(id=i, category='idea', age_hours=25) for i in range(1, 24)]
    line = sendguard.describe(dict(event=sendguard.FEEDBACK_ALERT_EVENT, detail=dict(reports=reports)))
    assert line.startswith('23 member reports have had no answer for more than 24 hours: report 1 (idea, 25 hours)')
    assert 'report 20 (idea' in line and 'report 21 (idea' not in line and 'and 3 more' in line
    one = sendguard.describe(dict(event=sendguard.FEEDBACK_ALERT_EVENT, detail=dict(reports=reports[:1])))
    assert one.startswith('1 member report has had no answer')
