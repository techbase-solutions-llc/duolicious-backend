"""Reports with a resolved state (TEC-1897; frames R.1 to R.5). A report is a
person_report row (migration 0072). Resolving records an outcome, who and
when on that row; Overview counts unresolved reports only.

"Email me when a report arrives" (R.2) is the owner's switch for the report
email that already goes to DUO_REPORT_EMAIL (antiabuse/lodgereport). It
starts on; only the owner's account may change it."""
from __future__ import annotations

from uuid import uuid4

import pytest

import antiabuse.lodgereport as lodgereport
from antiabuse.sql import Q_INSERT_SKIPPED
from database import api_tx
from service.admin import owner as owner_mod


def _report(a, b, reason='spam') -> None:
    """The app's own report write: the skip upsert POST /skip/by-uuid runs
    (antiabuse/lodgereport skip_by_uuid), without the report email. A
    second report on the same pair updates the row and moves created_at,
    and the 0072 trigger files a new person_report row."""
    with api_tx() as tx:
        tx.execute(Q_INSERT_SKIPPED, dict(subject_uuid=a['uuid'], object_uuid=b['uuid'],
                                          reported=True, report_reason=reason,
                                          is_bot_report=False))


def _reports(client, headers) -> dict:
    r = client.get('/admin/reports', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _mine(body, reporter) -> dict:
    return next(r for r in body['reports'] if r['reporter_uuid'] == reporter['uuid'])


def test_a_report_starts_unresolved_and_counts(client, admin_bearer, make_person):
    a, b = make_person(name='RepA'), make_person(name='RepB')
    before = _reports(client, admin_bearer)['unresolved']
    _report(a, b)
    body = _reports(client, admin_bearer)
    row = _mine(body, a)
    assert body['unresolved'] - before == 1
    assert row['outcome'] is None and row['resolved_at'] is None
    assert row['report_key'].startswith(f"{a['id']}-{b['id']}-")


def test_resolving_records_the_outcome_who_and_when(client, admin_bearer, make_person):
    a, b = make_person(name='RepC'), make_person(name='RepD')
    _report(a, b, reason='Rude in chat')
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    before = _reports(client, admin_bearer)['unresolved']
    r = client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                    json=dict(outcome='warned', note='Spoke to them'))
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    body = _reports(client, admin_bearer)
    row = _mine(body, a)
    assert body['unresolved'] == before - 1
    assert row['outcome'] == 'warned' and row['note'] == 'Spoke to them'
    assert row['resolved_by_name'] == 'CommunityAdmin'
    assert row['resolved_at'].endswith('+00:00')
    with api_tx('read committed') as tx:
        audit = tx.execute(
            """SELECT metadata FROM admin_audit_log WHERE action = 'resolve_report'
                ORDER BY created_at DESC LIMIT 1""").fetchone()['metadata']
    assert audit == {'report_key': key, 'outcome': 'warned'}
    assert 'Rude in chat' not in str(audit)


def test_a_report_resolves_once(client, admin_bearer, make_person):
    a, b = make_person(name='RepE'), make_person(name='RepF')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='dismissed')).status_code == 200
    r = client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                    json=dict(outcome='warned'))
    assert r.status_code == 409 and r.get_json() == {'error': 'already_resolved'}


def test_a_new_report_on_the_same_pair_is_unresolved_again(client, admin_bearer, make_person):
    a, b = make_person(name='RepG'), make_person(name='RepH')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer, json=dict(outcome='dismissed'))
    before = _reports(client, admin_bearer)['unresolved']
    _report(a, b, reason='Again')  # the upsert moves created_at: a new report
    body = _reports(client, admin_bearer)
    row = _mine(body, a)
    assert row['outcome'] is None and row['report_key'] != key
    assert body['unresolved'] - before == 1


def test_a_resolved_report_stays_after_an_unblock(client, admin_bearer, make_person):
    """Unblock deletes the skipped row; the report and its outcome stay."""
    a, b = make_person(name='RepK'), make_person(name='RepL')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer, json=dict(outcome='warned'))
    with api_tx() as tx:
        tx.execute("DELETE FROM skipped WHERE subject_person_id = %(a)s AND object_person_id = %(b)s",
                   dict(a=a['id'], b=b['id']))
    assert _mine(_reports(client, admin_bearer), a)['outcome'] == 'warned'


def test_bad_input_is_refused(client, admin_bearer, make_person):
    a, b = make_person(name='RepI'), make_person(name='RepJ')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='banned')).status_code == 400
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='warned', note='x' * 1001)).status_code == 400
    assert client.post('/admin/reports/1-2-20260101000000000000/resolve', headers=admin_bearer,
                       json=dict(outcome='warned')).status_code == 404
    assert client.post('/admin/reports/nonsense/resolve', headers=admin_bearer,
                       json=dict(outcome='warned')).status_code == 404


def test_only_an_admin_resolves(client, make_person, sign_in):
    mod = make_person(name='RepMod')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s", dict(i=mod['id']))
    headers = sign_in(mod)
    assert client.get('/admin/reports', headers=headers).status_code == 200
    assert client.post('/admin/reports/1-2-20260101000000000000/resolve', headers=headers,
                       json=dict(outcome='warned')).status_code == 403


# ---------------------------------------------------------------------------
# "Email me when a report arrives"
# ---------------------------------------------------------------------------

@pytest.fixture
def report_pref():
    """Puts the shared preference back as the test found it."""
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT enabled FROM admin_alert_pref WHERE alert = 'report'").fetchone()
    yield
    with api_tx() as tx:
        tx.execute("""INSERT INTO admin_alert_pref (alert, enabled) VALUES ('report', %(e)s)
                      ON CONFLICT (alert) DO UPDATE SET enabled = EXCLUDED.enabled""",
                   dict(e=row['enabled'] if row else True))


@pytest.fixture
def owner_bearer(make_person, sign_in, monkeypatch):
    """A signed-in admin who is the owner: the owner's address is swapped for
    this account's own, since the shared database may hold the real one."""
    email = f'owner-{uuid4().hex[:10]}@example.com'
    p = make_person(name='Owner', email=email)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
    monkeypatch.setattr(owner_mod, 'OWNER_EMAILS', frozenset({email}))
    return sign_in(p)


def test_the_preference_starts_on_and_only_the_owner_changes_it(
        client, admin_bearer, owner_bearer, report_pref):
    with api_tx() as tx:
        tx.execute("UPDATE admin_alert_pref SET enabled = TRUE WHERE alert = 'report'")
    assert client.get('/admin/alerts/report', headers=admin_bearer).get_json() == dict(
        enabled=True, can_change=False)
    assert client.post('/admin/alerts/report', headers=admin_bearer,
                       json=dict(enabled=False)).status_code == 403
    assert client.get('/admin/alerts/report', headers=owner_bearer).get_json() == dict(
        enabled=True, can_change=True)
    r = client.post('/admin/alerts/report', headers=owner_bearer, json=dict(enabled=False))
    assert r.status_code == 200 and r.get_json() == dict(enabled=False, can_change=True)
    assert client.get('/admin/alerts/report', headers=admin_bearer).get_json()['enabled'] is False
    with api_tx('read committed') as tx:
        audit = tx.execute(
            """SELECT metadata FROM admin_audit_log WHERE action = 'set_report_alert'
                ORDER BY created_at DESC LIMIT 1""").fetchone()['metadata']
    assert audit == {'enabled': False}
    assert client.post('/admin/alerts/report', headers=owner_bearer,
                       json=dict(enabled='yes')).status_code == 400


def test_the_preference_is_for_admins_only(client, make_person, sign_in):
    r = client.get('/admin/alerts/report', headers=sign_in(make_person(name='PrefMember')))
    assert r.status_code == 403


_REPORT = dict(reporter_id=101, reporter_uuid='3f9a2c1e-7b6d-4e5f-8a9b-0c1d2e3f4a5b',
               reporter_name='Miriam', reported_id=202,
               reported_uuid='9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d', reported_name='Samuel',
               message_count=0, reported_at=None)


def _sent_with_pref(monkeypatch, enabled) -> list:
    sent = []
    monkeypatch.setattr(lodgereport.aws_smtp, 'send', lambda **kw: sent.append(kw))
    with api_tx() as tx:
        if enabled is None:
            tx.execute("DELETE FROM admin_alert_pref WHERE alert = 'report'")
        else:
            tx.execute("""INSERT INTO admin_alert_pref (alert, enabled) VALUES ('report', %(e)s)
                          ON CONFLICT (alert) DO UPDATE SET enabled = EXCLUDED.enabled""",
                       dict(e=enabled))
    lodgereport._send_report_email(reason='spam-scam', report=dict(_REPORT), is_automoded_bot=False)
    return sent


def test_the_report_email_goes_while_the_preference_is_on(monkeypatch, report_pref):
    assert len(_sent_with_pref(monkeypatch, True)) == 1


def test_the_report_email_stops_while_the_preference_is_off(monkeypatch, report_pref):
    assert _sent_with_pref(monkeypatch, False) == []


def test_no_preference_row_reads_as_on(monkeypatch, report_pref):
    assert len(_sent_with_pref(monkeypatch, None)) == 1


def test_a_preference_that_cannot_be_read_still_sends(monkeypatch, report_pref):
    """The email was live before the switch: a database fault must not
    silence a report, so an unreadable preference reads as on."""
    import service.moderation as moderation
    from contextlib import contextmanager

    @contextmanager
    def broken(*a, **k):
        raise OSError('database down')
        yield

    monkeypatch.setattr(moderation, 'api_tx', broken)
    sent = []
    monkeypatch.setattr(lodgereport.aws_smtp, 'send', lambda **kw: sent.append(kw))
    lodgereport._send_report_email(reason='spam-scam', report=dict(_REPORT), is_automoded_bot=False)
    assert len(sent) == 1


def test_overview_pending_reports_leaves_out_a_resolved_report(client, admin_bearer, make_person):
    """The Overview card and the Needs you tile must agree once reports
    are resolved (review of TEC-1897, 21 Oct)."""
    from service.admin.queries.overview import Q_OVERVIEW_KPIS

    def pending() -> int:
        with api_tx('read committed') as tx:
            return tx.execute(Q_OVERVIEW_KPIS).fetchone()['pending_reports']

    a, b = make_person(name='RepY'), make_person(name='RepZ')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    before = pending()
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='dismissed')).status_code == 200
    assert pending() == before - 1
