"""A report outlives an unblock (TEC-1845 audit, serious 7).

A report was only the reporter's skipped row with reported = TRUE, and the
block is that same row, so Settings > Blocked > Unblock deleted the report
from the admin. Each report filed is now also kept in person_report (written
by a trigger on skipped), and the admin reads that. Unblock still deletes
the skipped row, so the two members can see each other again, which is what
the member asked for; the report stays where the owner can see it."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import pytest

import antiabuse.lodgereport as lodgereport
from database import api_tx

pytestmark = pytest.mark.usefixtures('no_limits')

REASON = 'harassment: Kept messaging after I said no.'


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(lodgereport, 'lodge_report', lambda **kw: None)


@pytest.fixture
def admin_headers(make_person) -> dict:
    admin = make_person(name='ReportsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def _reports_for(client, headers, reporter, reported) -> list[dict]:
    body = client.get('/admin/reports', headers=headers).get_json()
    return [r for r in body['reports']
            if r['reporter_uuid'] == reporter['uuid'] and r['reported_uuid'] == reported['uuid']]


def _pending_reports() -> int:
    from service.admin.queries import Q_OVERVIEW_KPIS
    with api_tx('read committed') as tx:
        return tx.execute(Q_OVERVIEW_KPIS).fetchone()['pending_reports']


def _ask(fn, x, y) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute(f'SELECT {fn}(%(x)s, %(y)s) AS v',
                          dict(x=x['id'], y=y['id'])).fetchone()['v']


def test_the_admin_still_lists_a_report_after_the_reporter_unblocks(client, unmatch_pair, admin_headers):
    p = unmatch_pair
    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': REASON}, headers=p.a_headers)
    assert r.status_code == 200
    listed = _reports_for(client, admin_headers, p.a, p.b)
    assert [x['reason'] for x in listed] == [REASON]
    pending = _pending_reports()

    assert client.post(f'/unskip/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200

    after = _reports_for(client, admin_headers, p.a, p.b)
    assert [x['reason'] for x in after] == [REASON], 'the report must stay in the admin'
    assert after[0]['created_at'] == listed[0]['created_at']
    assert _pending_reports() == pending


def test_after_an_unblock_the_two_can_see_each_other_again(client, unmatch_pair):
    p = unmatch_pair
    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': REASON}, headers=p.a_headers)
    assert _ask('is_blocked_pair', p.a, p.b) and _ask('is_blocked_pair', p.b, p.a)

    assert client.post(f'/unskip/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200

    assert client.get('/blocked', headers=p.a_headers).get_json() == []
    for x, y in ((p.a, p.b), (p.b, p.a)):
        assert not _ask('is_blocked_pair', x, y)
        assert not _ask('is_deck_suppressed', x, y)


def test_a_pass_is_not_a_report_and_a_second_report_is_a_second_record(client, unmatch_pair, admin_headers):
    p = unmatch_pair
    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={}, headers=p.a_headers)
    assert _reports_for(client, admin_headers, p.a, p.b) == []

    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': REASON}, headers=p.a_headers)
    # A plain pass on a pair already reported moves nothing: no record, and
    # the report keeps its time.
    first = _reports_for(client, admin_headers, p.a, p.b)
    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={}, headers=p.a_headers)
    assert _reports_for(client, admin_headers, p.a, p.b) == first

    client.post(f'/unskip/by-uuid/{p.b["uuid"]}', headers=p.a_headers)
    with api_tx() as tx:
        # A later report is a later record (the upsert stamps created_at).
        tx.execute("UPDATE person_report SET reported_at = reported_at - interval '1 day' "
                   "WHERE reporter_id = %(a)s AND reported_id = %(b)s", dict(a=p.a['id'], b=p.b['id']))
    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': 'spam-scam'}, headers=p.a_headers)
    assert [x['reason'] for x in _reports_for(client, admin_headers, p.a, p.b)] == ['spam-scam', REASON]


def test_the_migration_keeps_every_report_already_on_file(unmatch_pair):
    p = unmatch_pair
    with api_tx() as tx:
        tx.execute("ALTER TABLE skipped DISABLE TRIGGER USER")
        try:
            tx.execute(
                """INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
                   VALUES (%(a)s, %(b)s, TRUE, 'from before the deploy')""",
                dict(a=p.a['id'], b=p.b['id']))
        finally:
            tx.execute("ALTER TABLE skipped ENABLE TRIGGER USER")
    path = Path(__file__).resolve().parent.parent / 'migrations' / '0072_admin_serious_fixes.sql'
    for _ in range(2):
        with api_tx() as tx:
            tx.execute(path.read_text(encoding='utf-8'))
    with api_tx('read committed') as tx:
        rows = tx.execute(
            'SELECT reason FROM person_report WHERE reporter_id = %(a)s AND reported_id = %(b)s',
            dict(a=p.a['id'], b=p.b['id'])).fetchall()
    assert [r['reason'] for r in rows] == ['from before the deploy']
