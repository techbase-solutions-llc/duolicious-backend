"""The sendguard cron (send safeguards plan, 2 Nov 2026, task 1).

Each tick moves what the gate recorded in Redis (events, tallies, halts)
to Postgres, puts back any open halt Redis has lost, sends the owner one
alert covering every alertable event since the last tick, and writes the
heartbeat last, only when every step completed.

Redis is the per-test fakeredis from conftest. Nothing is mailed or pushed:
Smtp._try_send and the push sender are replaced."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

import smtp as smtp_mod
from database import api_tx
from smtp import guard
from service import sendguard


@pytest.fixture(autouse=True)
def _empty_tables():
    with api_tx() as tx:
        tx.execute('TRUNCATE send_guard_event, send_tally, send_guard_halt')
    yield


@pytest.fixture
def mail(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', lambda self, **kw: out.append(kw) or 'mid')
    return out


@pytest.fixture
def pushes(monkeypatch):
    out: list[tuple] = []

    def _push(person_id, payload, kind=None):
        out.append((person_id, payload, kind))
        return 1

    monkeypatch.setattr('service.notifications._send_to_user_blocking', _push)
    return out


def _db_events(name=None):
    with api_tx('read committed') as tx:
        rows = tx.execute('SELECT * FROM send_guard_event ORDER BY id').fetchall()
    return [r for r in rows if name is None or r['event'] == name]


def _send(to, kind='profile_resting', n=1):
    m = smtp_mod.make_aws_smtp()
    for _ in range(n):
        m.send(subject='Your Ahavah profile is resting', body='x', to_addr=to, kind=kind, retries=0, backoff=0)


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------

def test_events_move_to_postgres_and_leave_redis(mail, pushes):
    _send('one@ahavah-test.invalid', n=4)
    sendguard.tick()
    refused = _db_events('refused')
    assert len(refused) == 1 and refused[0]['kind'] == 'profile_resting' and refused[0]['rule'] == 'per_kind'
    assert refused[0]['alert'] is True and '@' not in (refused[0]['recipient'] or '')
    assert guard._redis().llen('sg:events') == 0
    sendguard.tick()
    assert len(_db_events('refused')) == 1


def test_events_recorded_while_redis_was_down_are_flushed(mail, pushes):
    guard._local_events.append(json.dumps(guard._event('redis_down', channel='guard', alert=True)))
    sendguard.tick()
    assert len(_db_events('redis_down')) == 1


def test_tallies_move_to_send_tally(mail, pushes):
    _send('tally@ahavah-test.invalid', n=4)
    sendguard.tick()
    sendguard.tick()
    with api_tx('read committed') as tx:
        rows = {(r['channel'], r['kind'], r['outcome']): r['count']
                for r in tx.execute('SELECT * FROM send_tally').fetchall()}
    assert rows[('email', 'profile_resting', 'sent')] == 3
    assert rows[('email', 'profile_resting', 'refused')] == 1


def test_old_events_are_deleted_after_90_days(mail, pushes):
    with api_tx() as tx:
        tx.execute("INSERT INTO send_guard_event (at, channel, event) VALUES (NOW() - interval '91 days', 'email', 'refused')")
        tx.execute("INSERT INTO send_guard_event (at, channel, event) VALUES (NOW() - interval '89 days', 'email', 'refused')")
    sendguard.tick()
    assert len(_db_events('refused')) == 1


# ---------------------------------------------------------------------------
# halts
# ---------------------------------------------------------------------------

def _open_halts():
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM send_guard_halt WHERE cleared_at IS NULL ORDER BY id').fetchall()


def test_a_halt_is_recorded_and_one_redis_lost_comes_back(mail, pushes):
    for who in ('h1', 'h2', 'h3'):
        _send(f'{who}@ahavah-test.invalid', n=4)
    sendguard.tick()
    halts = _open_halts()
    assert [(h['channel'], h['scope'], h['kind']) for h in halts] == [('email', 'kind', 'profile_resting')]
    guard._redis().delete('sg:halt:kind:profile_resting')      # Redis restarted
    sendguard.tick()
    assert guard._redis().get('sg:halt:kind:profile_resting') is not None
    assert len(_open_halts()) == 1


def test_clearing_records_who_and_the_cron_does_not_undo_it(mail, pushes):
    guard.set_halt('email', 'profile_resting', reason='test')
    sendguard.tick()
    assert sendguard.clear_halt('email', 'profile_resting', by='owner') is True
    sendguard.tick()
    assert guard._redis().get('sg:halt:kind:profile_resting') is None
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM send_guard_halt').fetchone()
    assert row['cleared_by'] == 'owner' and row['cleared_at'] is not None
    cleared = _db_events('cleared')
    assert len(cleared) == 1 and cleared[0]['detail']['by'] == 'owner'


def test_a_halt_cleared_in_postgres_before_the_cron_saw_its_redis_key_is_removed(mail, pushes):
    guard.set_halt('email', None, reason='test')
    sendguard.tick()
    # The clear wrote Postgres, then the process died before deleting Redis.
    with api_tx() as tx:
        tx.execute("UPDATE send_guard_halt SET cleared_at = NOW(), cleared_by = 'owner'")
    sendguard.tick()
    assert guard._redis().get('sg:halt:all') is None


def test_clearing_the_global_halt(mail, pushes):
    guard.set_halt('email', None, reason='ceiling')
    guard.set_halt('push', None, reason='ceiling')
    sendguard.tick()
    assert sendguard.clear_halt('email', None, by='owner')
    assert guard._redis().get('sg:halt:all') is None
    assert guard._redis().get('sg:p:halt:all') is not None
    assert not sendguard.clear_halt('email', None, by='owner')


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------

def test_one_alert_covers_every_alertable_event_since_the_last_tick(mail, pushes, monkeypatch):
    monkeypatch.setenv('AHAVAH_ALERT_EMAILS', 'owner-a@ahavah-test.invalid owner-b@ahavah-test.invalid')
    monkeypatch.setenv('AHAVAH_ALERT_PUSH_PERSON_ID', '18')
    for who in ('a1', 'a2', 'a3'):
        _send(f'{who}@ahavah-test.invalid', n=4)
    sent_before = len(mail)
    sendguard.tick()
    alerts = mail[sent_before:]
    assert [m['to_addr'] for m in alerts] == ['owner-a@ahavah-test.invalid', 'owner-b@ahavah-test.invalid']
    assert alerts[0]['subject'] == 'Ahavah mail guard: 2 alerts'
    body = alerts[0]['body']
    assert 'profile_resting' in body and 'halted' in body
    assert pushes and pushes[0][0] == 18 and pushes[0][2] == 'guard_alert'
    # Nothing new: no alert.
    sendguard.tick()
    assert len(mail) == sent_before + 2 and len(pushes) == 1


def test_no_alert_when_nothing_alertable(mail, pushes):
    _send('quiet@ahavah-test.invalid', n=3)
    sendguard.tick()
    assert len(mail) == 3 and pushes == []


def test_the_alert_copy_follows_the_owners_rules(mail, pushes):
    for name in ('dry_run_send', 'essential_cap', 'ceiling_shadow', 'bulk_window_ignored', 'redis_down',
                 'guard_unavailable', 'halt', 'refused', 'shadow_ended'):
        guard.record_event(name, channel='email', kind='k', alert=True, rule='r', scope='kind')
    sendguard.tick()
    body = mail[-1]['body'] + mail[-1]['subject'] + pushes[0][1]['title'] + pushes[0][1]['body']
    assert '—' not in body and '!' not in body and 'dating' not in body.lower()


def test_a_failed_alert_email_is_recorded_and_the_tick_still_completes(pushes, monkeypatch):
    def _boom(self, **kw):
        raise RuntimeError('resend down')

    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', _boom)
    monkeypatch.setattr(sendguard, 'ALERT_RETRY_BACKOFF', 0)
    guard.record_event('dry_run_send', channel='email', kind='k', alert=True)
    sendguard.tick()
    failed = _db_events('alert_failed')
    assert len(failed) == 1 and failed[0]['channel'] == 'email'
    assert guard._redis().get('sg:heartbeat') is not None


def test_a_push_alert_that_reaches_no_device_is_recorded(mail, monkeypatch):
    monkeypatch.setattr('service.notifications._send_to_user_blocking', lambda *a, **k: 0)
    guard.record_event('dry_run_send', channel='email', kind='k', alert=True)
    sendguard.tick()
    failed = _db_events('alert_failed')
    assert len(failed) == 1 and failed[0]['channel'] == 'push'


def test_the_heartbeat_is_not_written_when_a_tick_raises_part_way(mail, pushes, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError('postgres hiccup')

    monkeypatch.setattr(sendguard, '_sync_halts', _boom)
    with pytest.raises(RuntimeError):
        sendguard.tick()
    assert guard._redis().get('sg:heartbeat') is None


def test_the_20th_alert_of_a_day_says_it_is_the_last(mail, pushes, monkeypatch):
    monkeypatch.setenv('AHAVAH_ALERT_EMAILS', 'admin@techbaseltd.com')
    for _ in range(21):
        guard.record_event('dry_run_send', channel='email', kind='k', alert=True)
        sendguard.tick()
    alerts = [m for m in mail if m['subject'].startswith('Ahavah mail guard')]
    assert len(alerts) == 20
    assert 'last alert email today' in alerts[19]['body']
    assert 'last alert email today' not in alerts[18]['body']
    assert len(_db_events('alert_capped')) == 1


def test_with_redis_down_the_tick_records_and_alerts_once_per_outage(mail, pushes, monkeypatch):
    """Review, 2 Nov 2026: the tick failed at its first Redis read, so the
    plan's redis_down alert was never stored or sent while Redis was down,
    and nothing told the owner until the outside watchdog exists."""
    class _Down:
        def __getattr__(self, name):
            def _fail(*a, **k):
                raise ConnectionError('redis down')
            return _fail

    monkeypatch.setattr(sendguard, '_redis_outage_alerted', False)
    guard.set_redis(_Down())
    for _ in range(3):
        with pytest.raises(ConnectionError):
            sendguard.tick()
    alerts = [m for m in mail if m['subject'].startswith('Ahavah mail guard')]
    assert len(alerts) == 1 and 'Redis could not be reached' in alerts[0]['body']
    assert len(pushes) == 1
    assert _db_events('redis_down')
    # Something else alertable during the outage still alerts.
    guard._local_events.append(json.dumps(guard._event('dry_run_send', channel='email', kind='k', alert=True)))
    with pytest.raises(ConnectionError):
        sendguard.tick()
    alerts = [m for m in mail if m['subject'].startswith('Ahavah mail guard')]
    assert len(alerts) == 2 and 'Redis' not in alerts[1]['body'].split('</p>')[0]


def test_the_alert_push_stops_with_the_alert_email_at_the_daily_cap(mail, pushes, monkeypatch):
    """Review, 2 Nov 2026: the push to the owner had no cap, so an event
    source that never stops pushed to the owner's phone every minute."""
    monkeypatch.setenv('AHAVAH_ALERT_EMAILS', 'admin@techbaseltd.com')
    for _ in range(30):
        guard.record_event('dry_run_send', channel='email', kind='k', alert=True)
        sendguard.tick()
    assert len([m for m in mail if m['subject'].startswith('Ahavah mail guard')]) == 20
    assert len(pushes) == 20


def test_the_end_of_the_trial_week_alerts_once(mail, pushes, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', '2026-11-10')
    with freeze_time('2026-11-09 12:00:00'):
        sendguard.tick()
    assert _db_events('shadow_ended') == []
    with freeze_time('2026-11-10 12:00:00'):
        sendguard.tick()
        sendguard.tick()
    assert len(_db_events('shadow_ended')) == 1
    assert any('now stop' in m['body'] for m in mail)


# ---------------------------------------------------------------------------
# clearing from outside the cron
# ---------------------------------------------------------------------------

def test_the_admin_route_clears_a_halt_and_records_the_admin(client, admin_headers, mail, pushes):
    guard.set_halt('email', 'profile_resting', reason='test')
    sendguard.tick()
    r = client.post('/admin/system/mail-guard/clear', json={'kind': 'profile_resting'}, headers=admin_headers)
    assert r.status_code == 200 and r.get_json() == {'cleared': True}
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM send_guard_halt').fetchone()
    assert row['cleared_by'].startswith('admin:')


def test_the_admin_route_needs_an_admin_and_one_target(client, admin_headers, make_person, sign_in):
    member = sign_in(make_person(name='NotAdmin'))
    assert client.post('/admin/system/mail-guard/clear', json={'all': True}, headers=member).status_code == 403
    assert client.post('/admin/system/mail-guard/clear', json={}, headers=admin_headers).status_code == 400
    assert client.post('/admin/system/mail-guard/clear', json={'all': True, 'kind': 'x'},
                       headers=admin_headers).status_code == 400
    assert client.post('/admin/system/mail-guard/clear', json={'all': True, 'channel': 'fax'},
                       headers=admin_headers).status_code == 400


def test_the_clear_script(mail, pushes):
    from scripts import mail_guard_clear
    guard.set_halt('push', None, reason='test')
    sendguard.tick()
    assert mail_guard_clear.main(['--all', '--push', '--by', 'owner']) == 0
    assert guard._redis().get('sg:p:halt:all') is None
    assert mail_guard_clear.main(['--all', '--push', '--by', 'owner']) == 1


def test_the_halt_script(mail, pushes):
    from scripts import mail_guard_halt
    assert mail_guard_halt.main(['--all', '--reason', 'manual stop']) == 0
    assert guard._redis().get('sg:halt:all') is not None
    sendguard.tick()
    assert len(_open_halts()) == 1
