"""The exit question (TEC-2158): why a member is leaving, kept without their
name or email.

DELETE /account takes an optional {reason, note}. The answer is written in
the soft delete's transaction, best-effort: nothing about it can block or
fail a deletion, or the sign-in that keeps the account. When the 7 days pass
the row stays with no person; when the member keeps the account the row is
closed (kept_at set, person cleared). GET /admin/exit-answers shows counts
and the latest answers with nothing that names a member."""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from database import api_tx

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0100_exit_answer.sql'
CLIENT = '45.33.20.11'
REASONS = ['met_here', 'met_elsewhere', 'few_people', 'not_expected', 'break', 'other']
BROKEN_KEEP = ('UPDATE exit_answer_missing SET kept_at = NOW() '
               'WHERE person_id = %(person_id)s')


@pytest.fixture(autouse=True)
def exit_answer_cleanup():
    """Rows outlive their person (ON DELETE SET NULL), so make_person's
    teardown does not remove them."""
    with api_tx() as tx:
        before = tx.execute('SELECT COALESCE(MAX(id), 0) AS m FROM exit_answer').fetchone()['m']
    yield
    with api_tx() as tx:
        tx.execute('DELETE FROM exit_answer WHERE id > %(m)s', dict(m=before))


def _rows(person) -> list[dict]:
    with api_tx() as tx:
        return tx.execute(
            'SELECT * FROM exit_answer WHERE person_id = %(p)s ORDER BY id',
            dict(p=person['id'])).fetchall()


def _by_note(note: str) -> list[dict]:
    with api_tx() as tx:
        return tx.execute('SELECT * FROM exit_answer WHERE note = %(n)s ORDER BY id',
                          dict(n=note)).fetchall()


def _person(person) -> dict:
    with api_tx() as tx:
        return tx.execute(
            'SELECT email, activated, deletion_requested_at FROM person WHERE id = %(p)s',
            dict(p=person['id'])).fetchone()


def _pending(person) -> bool:
    row = _person(person)
    return row['activated'] is False and row['deletion_requested_at'] is not None


def _delete(client, sign_in, person, **kw):
    r = client.delete('/account', headers=sign_in(person), **kw)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def _otp_sign_in(client, signup_env, email):
    r = signup_env.request(email, ip=CLIENT)
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    return client.post('/check-otp', json=dict(email=email, otp='000000'),
                       headers={'Authorization': f'Bearer {token}'},
                       environ_base={'REMOTE_ADDR': CLIENT})


# --- the migration --------------------------------------------------------

def test_the_migration_can_run_twice():
    sql = MIGRATION.read_text(encoding='utf-8')
    with api_tx() as tx:
        tx.execute(sql)
        tx.execute(sql)
        cols = {r['column_name'] for r in tx.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'exit_answer'").fetchall()}
    assert cols == {'id', 'person_id', 'reason', 'note', 'gender', 'member_band',
                    'had_premium', 'created_at', 'kept_at'}


# --- DELETE /account ------------------------------------------------------

def test_the_answer_is_stored_with_the_delete(client, sign_in, make_person):
    p = make_person(name='Leaver', gender='Woman')
    with api_tx() as tx:
        tx.execute("UPDATE person SET entitlements = ARRAY['premium']::TEXT[], "
                   "sign_up_time = LOCALTIMESTAMP - INTERVAL '70 days' WHERE id = %(p)s",
                   dict(p=p['id']))

    _delete(client, sign_in, p, json=dict(reason='met_here', note='  We met in March.  '))

    assert _pending(p)
    rows = _rows(p)
    assert len(rows) == 1
    row = rows[0]
    assert row['reason'] == 'met_here'
    assert row['note'] == 'We met in March.'
    assert row['gender'] == 'Woman'
    assert row['member_band'] == '1_to_6_months'
    assert row['had_premium'] is True
    assert row['kept_at'] is None


@pytest.mark.parametrize('age, band', [
    ('2 days', 'under_1_month'),
    ('3 months', '1_to_6_months'),
    ('2 years', 'over_6_months'),
])
def test_time_as_a_member_is_kept_as_a_band(client, sign_in, make_person, age, band):
    p = make_person(name='Banded')
    with api_tx() as tx:
        tx.execute("UPDATE person SET sign_up_time = LOCALTIMESTAMP - %(age)s::interval "
                   "WHERE id = %(p)s", dict(p=p['id'], age=age))

    _delete(client, sign_in, p, json=dict(reason='break'))

    row = _rows(p)[0]
    assert row['member_band'] == band
    assert row['gender'] == 'Man' and row['had_premium'] is False and row['note'] is None


@pytest.mark.parametrize('kw', [
    {},
    dict(json={}),
    dict(json=[1, 2]),
    dict(json='met_here'),
    dict(data='{not json', content_type='application/json'),
    dict(data='reason=met_here', content_type='application/x-www-form-urlencoded'),
    dict(json=dict(note='a note and no reason')),
])
def test_no_answer_or_a_bad_body_still_deletes_and_stores_nothing(
        client, sign_in, make_person, kw):
    p = make_person(name='NoAnswer')
    _delete(client, sign_in, p, **kw)
    assert _pending(p)
    assert _rows(p) == []


@pytest.mark.parametrize('reason', ['nope', '', None, 7, ['met_here'], 'MET_HERE'])
def test_an_unknown_reason_deletes_and_stores_nothing(client, sign_in, make_person, reason):
    p = make_person(name='Unknown')
    _delete(client, sign_in, p, json=dict(reason=reason, note='kept out'))
    assert _pending(p)
    assert _rows(p) == []


def test_the_note_is_cut_to_300_characters(client, sign_in, make_person):
    p = make_person(name='Wordy')
    _delete(client, sign_in, p, json=dict(reason='other', note='  ' + 'é' * 400))
    row = _rows(p)[0]
    assert row['note'] == 'é' * 300


@pytest.mark.parametrize('note', ['', '   \n ', None, 12, ['x']])
def test_an_empty_or_odd_note_is_dropped_and_the_reason_kept(
        client, sign_in, make_person, note):
    p = make_person(name='Quiet')
    _delete(client, sign_in, p, json=dict(reason='few_people', note=note))
    row = _rows(p)[0]
    assert row['reason'] == 'few_people' and row['note'] is None


def test_a_note_postgres_cannot_hold_still_deletes(client, sign_in, make_person):
    p = make_person(name='Nul')
    _delete(client, sign_in, p, json=dict(reason='other', note='a' + chr(0) + 'b'))
    assert _pending(p)
    assert [r['note'] for r in _rows(p)] == ['ab']


def test_older_premium_counts_as_premium(client, sign_in, make_person):
    p = make_person(name='Gold')
    with api_tx() as tx:
        tx.execute('UPDATE person SET has_gold = TRUE WHERE id = %(p)s', dict(p=p['id']))
    _delete(client, sign_in, p, json=dict(reason='break'))
    assert _rows(p)[0]['had_premium'] is True


def test_a_lock_on_the_answer_never_holds_up_the_deletion(client, sign_in, make_person):
    """Another transaction holds the member's open row. The answer gives
    up after a second and the deletion goes through."""
    import time

    p = make_person(name='Locked')
    with api_tx() as tx:
        tx.execute("INSERT INTO exit_answer (person_id, reason) VALUES (%(p)s, 'break')",
                   dict(p=p['id']))
    headers = sign_in(p)
    # The holder needs its own connection: api_tx shares one connection per
    # process behind a lock, so holding it here would block the request.
    import psycopg
    import database
    with psycopg.connect(database._api_conninfo) as holder:
        holder.execute('SELECT 1 FROM exit_answer WHERE person_id = %(p)s FOR UPDATE',
                       dict(p=p['id']))
        started = time.monotonic()
        r = client.delete('/account', headers=headers, json=dict(reason='other'))
        waited = time.monotonic() - started
        holder.rollback()
    assert r.status_code == 200, r.get_data(as_text=True)
    assert waited < 10
    assert _pending(p)
    assert [row['reason'] for row in _rows(p)] == ['break'], 'the new answer was let go'


def test_the_lock_timeout_is_put_back(make_person):
    from service.person import exit_answer

    p = make_person(name='Timeout')
    with api_tx() as tx:
        tx.execute("SET LOCAL lock_timeout = '7s'")
        assert exit_answer.record(tx, p['id'], dict(reason='break')) is True
        assert tx.execute("SELECT current_setting('lock_timeout') AS v").fetchone()['v'] == '7s'
        assert exit_answer.mark_kept(tx, p['id']) is True
        assert tx.execute("SELECT current_setting('lock_timeout') AS v").fetchone()['v'] == '7s'


@pytest.mark.parametrize('role', ['admin', 'mod', 'tester'])
def test_staff_and_testers_store_nothing(client, sign_in, make_person, role):
    p = make_person(name='Staff')
    with api_tx() as tx:
        tx.execute('UPDATE person SET roles = ARRAY[%(r)s]::TEXT[] WHERE id = %(p)s',
                   dict(r=role, p=p['id']))
    _delete(client, sign_in, p, json=dict(reason='break', note='testing'))
    assert _pending(p)
    assert _rows(p) == []


def test_a_failing_insert_never_fails_the_deletion(
        client, sign_in, make_person, monkeypatch, capsys):
    from service.person import exit_answer

    monkeypatch.setattr(exit_answer, 'Q_INSERT',
                        'INSERT INTO exit_answer_missing (person_id, reason, note) '
                        'VALUES (%(person_id)s, %(reason)s, %(note)s)')
    p = make_person(name='Unlucky')
    note = f'secret-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='other', note=note))

    assert _pending(p), 'the soft delete commits although the answer could not be written'
    assert _rows(p) == []
    with api_tx() as tx:
        sessions = tx.execute('SELECT count(*) AS n FROM duo_session WHERE person_id = %(p)s',
                              dict(p=p['id'])).fetchone()['n']
    assert sessions == 0, 'the rest of the deletion ran'
    logged = [line for line in capsys.readouterr().out.splitlines()
              if line.startswith('exit_answer:')]
    assert logged == ['exit_answer: record failed: UndefinedTable'],         'the failure is logged, with the step and the error class and no member data'


def test_an_open_answer_is_closed_before_a_new_one(client, sign_in, make_person):
    """The unique index allows one open row a person. A leftover open row
    (kept without the keep being recorded) must not lose the new answer."""
    p = make_person(name='Leftover')
    old = f'old-{uuid4()}'
    with api_tx() as tx:
        tx.execute("INSERT INTO exit_answer (person_id, reason, note) "
                   "VALUES (%(p)s, 'break', %(n)s)", dict(p=p['id'], n=old))

    new = f'new-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='not_expected', note=new))

    assert [(r['reason'], r['note']) for r in _rows(p)] == [('not_expected', new)]
    closed = _by_note(old)[0]
    assert closed['person_id'] is None and closed['kept_at'] is not None


# --- after the delete -----------------------------------------------------

def test_the_hard_delete_keeps_the_answer_with_no_person(client, sign_in, make_person):
    from service.cron.pendingdeletion import hard_delete_expired_once

    p = make_person(name='Gone')
    note = f'gone-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='met_elsewhere', note=note))
    with api_tx() as tx:
        tx.execute("UPDATE person SET deletion_requested_at = NOW() - INTERVAL '8 days', "
                   "sign_in_time = NOW() - INTERVAL '9 days' WHERE id = %(p)s",
                   dict(p=p['id']))

    asyncio.run(hard_delete_expired_once())

    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM person WHERE id = %(p)s',
                          dict(p=p['id'])).fetchone() is None
    rows = _by_note(note)
    assert len(rows) == 1
    assert rows[0]['person_id'] is None and rows[0]['kept_at'] is None
    assert rows[0]['reason'] == 'met_elsewhere'


def test_cancelling_the_deletion_marks_the_answer_kept(client, sign_in, make_person):
    p = make_person(name='Stayer')
    note = f'stay-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='break', note=note))

    r = client.post('/account/cancel-deletion', headers=sign_in(p))
    assert r.status_code == 200 and r.get_json() == {'ok': True, 'restored': True}

    rows = _by_note(note)
    assert len(rows) == 1
    assert rows[0]['kept_at'] is not None and rows[0]['person_id'] is None
    assert _rows(p) == []


def test_signing_in_again_marks_the_answer_kept(client, signup_env, sign_in, make_person):
    p = make_person(name='Returner')
    note = f'back-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='break', note=note))

    ok = _otp_sign_in(client, signup_env, _person(p)['email'])
    assert ok.status_code == 200, ok.get_data(as_text=True)

    assert _person(p)['deletion_requested_at'] is None
    rows = _by_note(note)
    assert len(rows) == 1
    assert rows[0]['kept_at'] is not None and rows[0]['person_id'] is None


def test_a_failing_keep_never_blocks_sign_in(client, signup_env, sign_in, make_person,
                                             monkeypatch):
    from service.person import exit_answer

    p = make_person(name='StillIn')
    _delete(client, sign_in, p, json=dict(reason='break'))
    monkeypatch.setattr(exit_answer, 'Q_MARK_KEPT', BROKEN_KEEP)

    ok = _otp_sign_in(client, signup_env, _person(p)['email'])

    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.get_json()['onboarded'] is True
    row = _person(p)
    assert row['activated'] is True and row['deletion_requested_at'] is None
    assert len(_rows(p)) == 1, 'the keep was tried and failed; the answer is as it was'


def test_a_failing_keep_never_blocks_cancel_deletion(client, sign_in, make_person,
                                                     monkeypatch):
    from service.person import exit_answer

    p = make_person(name='StillHere')
    _delete(client, sign_in, p, json=dict(reason='break'))
    monkeypatch.setattr(exit_answer, 'Q_MARK_KEPT', BROKEN_KEEP)

    r = client.post('/account/cancel-deletion', headers=sign_in(p))

    assert r.status_code == 200 and r.get_json() == {'ok': True, 'restored': True}
    assert _person(p)['deletion_requested_at'] is None


def test_a_second_deletion_makes_a_second_row(client, sign_in, make_person):
    p = make_person(name='Twice')
    first, second = f'first-{uuid4()}', f'second-{uuid4()}'
    _delete(client, sign_in, p, json=dict(reason='break', note=first))
    assert client.post('/account/cancel-deletion', headers=sign_in(p)).status_code == 200
    _delete(client, sign_in, p, json=dict(reason='met_here', note=second))

    kept, waiting = _by_note(first)[0], _by_note(second)[0]
    assert kept['kept_at'] is not None and kept['person_id'] is None
    assert waiting['kept_at'] is None and waiting['person_id'] == p['id']
    assert waiting['id'] != kept['id']


# --- GET /admin/exit-answers ----------------------------------------------

def _admin_view(client, admin_bearer) -> dict:
    r = client.get('/admin/exit-answers', headers=admin_bearer)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _counts(view: dict) -> dict:
    return {r['reason']: (r['all_time'], r['last_90_days']) for r in view['counts']}


def test_the_admin_route_refuses_everyone_but_an_admin(client, sign_in, make_person):
    assert client.get('/admin/exit-answers').status_code in (400, 401, 403)
    member = make_person(name='Member')
    assert client.get('/admin/exit-answers', headers=sign_in(member)).status_code == 403
    mod = make_person(name='Mod')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(p)s",
                   dict(p=mod['id']))
    assert client.get('/admin/exit-answers', headers=sign_in(mod)).status_code == 403


def test_the_admin_view_counts_and_lists_without_naming_anyone(
        client, sign_in, make_person, admin_bearer):
    before = _admin_view(client, admin_bearer)

    gone = make_person(name='GoneForGood', gender='Woman')
    kept = make_person(name='KeptAccount')
    waiting = make_person(name='StillWaiting')
    notes = {k: f'{k}-{uuid4()}' for k in ('gone', 'kept', 'waiting', 'old')}
    _delete(client, sign_in, gone, json=dict(reason='met_here', note=notes['gone']))
    _delete(client, sign_in, kept, json=dict(reason='break', note=notes['kept']))
    _delete(client, sign_in, waiting, json=dict(reason='other', note=notes['waiting']))
    assert client.post('/account/cancel-deletion', headers=sign_in(kept)).status_code == 200
    with api_tx() as tx:
        # What the hard delete leaves: the row, with no person.
        tx.execute('UPDATE exit_answer SET person_id = NULL WHERE note = %(n)s',
                   dict(n=notes['gone']))
        tx.execute(
            "INSERT INTO exit_answer (reason, note, gender, member_band, had_premium, "
            "created_at) VALUES ('few_people', %(n)s, 'Man', 'over_6_months', FALSE, "
            "NOW() - INTERVAL '100 days')", dict(n=notes['old']))
        month = tx.execute(
            "SELECT to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM') AS m").fetchone()['m']

    view = _admin_view(client, admin_bearer)

    assert set(view) == {'waiting', 'counts', 'answers'}
    assert [r['reason'] for r in view['counts']] == REASONS, 'every reason, in the app order'
    was, now = _counts(before), _counts(view)
    delta = {k: (now[k][0] - was[k][0], now[k][1] - was[k][1]) for k in REASONS}
    assert delta == {
        'met_here': (1, 1), 'break': (1, 1), 'few_people': (1, 0),
        'other': (0, 0),  # still waiting on the 7 days
        'met_elsewhere': (0, 0), 'not_expected': (0, 0),
    }
    assert view['waiting'] - before['waiting'] == 1

    assert len(view['answers']) <= 50
    by_note = {a['note']: a for a in view['answers']}
    assert notes['waiting'] not in by_note, 'a waiting answer is not shown'
    assert by_note[notes['gone']] == dict(
        month=month, reason='met_here', note=notes['gone'], gender='Woman',
        member_band='under_1_month', had_premium=False, state='deleted')
    assert by_note[notes['kept']]['state'] == 'kept'
    listed = [a['note'] for a in view['answers']]
    assert listed.index(notes['kept']) < listed.index(notes['gone']), 'newest first'

    fields = {'month', 'reason', 'note', 'gender', 'member_band', 'had_premium', 'state'}
    assert all(set(a) == fields for a in view['answers'])
    assert all(a['state'] in ('deleted', 'kept') for a in view['answers'])
    assert all(len(a['month']) == 7 for a in view['answers']), 'the month, never the day'
    body = client.get('/admin/exit-answers', headers=admin_bearer).get_data(as_text=True)
    for person in (gone, kept, waiting):
        assert person['uuid'] not in body
        assert _person(person)['email'] not in body
    for name in ('GoneForGood', 'KeptAccount', 'StillWaiting'):
        assert name not in body


def test_the_admin_view_lists_the_latest_50(client, admin_bearer):
    tag = f'bulk-{uuid4()}'
    with api_tx() as tx:
        tx.execute(
            "INSERT INTO exit_answer (reason, note, created_at) "
            "SELECT 'other', %(t)s || '-' || n, NOW() + (n || ' seconds')::interval "
            "FROM generate_series(1, 55) AS n", dict(t=tag))

    answers = _admin_view(client, admin_bearer)['answers']

    assert len(answers) == 50
    assert [a['note'] for a in answers] == [f'{tag}-{n}' for n in range(55, 5, -1)]
