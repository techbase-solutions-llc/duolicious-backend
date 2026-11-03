"""GET /internal/send-stats (send safeguards plan, 2 Nov 2026, task 4).

The outside watchdog (techbase-solutions-llc/mail-watchdog) reads this every
30 minutes with its own read-only secret, AHAVAH_SEND_STATS_SECRET in header
X-Send-Stats. The growth cron secret does not open it, and its secret opens
nothing else. No field may carry an address."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from smtp import guard

PATH = '/internal/send-stats'
SECRET = 'test-send-stats-secret'


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_STATS_SECRET', SECRET)
    with api_tx() as tx:
        tx.execute('TRUNCATE send_guard_event, send_tally, send_guard_halt')
    yield


def _get(client, **headers):
    return client.get(PATH, headers=headers)


def _ok(client):
    r = _get(client, **{'X-Send-Stats': SECRET})
    assert r.status_code == 200
    return r.get_json()


# ---------------------------------------------------------------------------
# who may read it
# ---------------------------------------------------------------------------

def test_no_header_is_refused(client):
    assert _get(client).status_code == 403


def test_a_wrong_secret_is_refused(client):
    assert _get(client, **{'X-Send-Stats': 'wrong'}).status_code == 403


def test_an_unset_secret_refuses_everyone(client, monkeypatch):
    monkeypatch.delenv('AHAVAH_SEND_STATS_SECRET')
    assert _get(client, **{'X-Send-Stats': ''}).status_code == 403
    assert _get(client, **{'X-Send-Stats': SECRET}).status_code == 403


def test_the_growth_cron_secret_does_not_open_it(client):
    assert _get(client, **{'X-Growth-Cron': 'test-cron-secret'}).status_code == 403


def test_the_stats_secret_opens_no_growth_route(client):
    r = client.get('/admin/growth/queue', headers={'X-Send-Stats': SECRET})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# what it says
# ---------------------------------------------------------------------------

def _tally(hours_ago, channel, kind, outcome, count):
    hour = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0)
    with api_tx() as tx:
        tx.execute("""INSERT INTO send_tally (hour, channel, kind, outcome, count)
                      VALUES (%(h)s, %(c)s, %(k)s, %(o)s, %(n)s)""",
                   dict(h=hour, c=channel, k=kind, o=outcome, n=count))


def test_the_figures_match_send_tally(client):
    _tally(0, 'email', 'e2', 'sent', 5)
    _tally(0, 'email', 'e2', 'refused', 1)
    _tally(5, 'email', 'e2', 'sent', 7)
    _tally(30, 'email', 'e2', 'failed', 2)
    _tally(24 * 8, 'email', 'e2', 'sent', 100)          # outside 7 days
    _tally(0, 'push', 'chat_message', 'sent', 9)
    d = _ok(client)
    assert d['email']['1h']['e2'] == dict(sent=5, refused=1, failed=0)
    assert d['email']['24h']['e2'] == dict(sent=12, refused=1, failed=0)
    assert d['email']['7d']['e2'] == dict(sent=12, refused=1, failed=2)
    assert d['push']['1h']['chat_message']['sent'] == 9


def test_redis_figures_this_hour_are_included_before_the_cron_flushes_them(client):
    guard._redis().hset(f'sg:tally:{guard.utc_hour()}', 'email|welcome|sent', 4)
    assert _ok(client)['email']['1h']['welcome']['sent'] == 4


def test_halts_events_and_heartbeat(client):
    with api_tx() as tx:
        tx.execute("""INSERT INTO send_guard_halt (channel, scope, kind, set_at, reason)
                      VALUES ('email', 'kind', 'profile_resting', NOW(), '3 people over the limit')""")
        for ev in ('dry_run_send', 'essential_cap', 'alert_failed', 'alert_failed', 'refused'):
            tx.execute("INSERT INTO send_guard_event (channel, event, kind) VALUES ('email', %(e)s, 'k')",
                       dict(e=ev))
        tx.execute("INSERT INTO send_guard_event (at, channel, event) VALUES (NOW() - interval '2 days', 'email', 'alert_failed')")
    guard._redis().set('sg:heartbeat', (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat())
    d = _ok(client)
    assert d['open_halts'] == [dict(channel='email', scope='kind', kind='profile_resting',
                                    set_at=d['open_halts'][0]['set_at'], reason='3 people over the limit')]
    assert d['events_24h']['dry_run_send'] == 1 and d['events_24h']['essential_cap'] == 1
    assert d['events_24h']['alert_failed'] == 2 and d['alert_failed_24h'] == 2
    assert len(d['recent_events']) == 6 and all('recipient' not in e for e in d['recent_events'])
    assert 85 <= d['heartbeat_age_seconds'] <= 150
    assert d['redis'] == 'ok'


def test_a_heartbeat_never_written_is_null(client):
    assert _ok(client)['heartbeat_age_seconds'] is None


def test_redis_down_still_answers_200_from_postgres(client, monkeypatch):
    class _Dead:
        def __getattr__(self, name):
            def _raise(*a, **k):
                raise ConnectionError('down')
            return _raise

    _tally(0, 'email', 'e2', 'sent', 3)
    monkeypatch.setattr(guard, '_redis_client', _Dead())
    d = _ok(client)
    assert d['redis'] == 'unreachable' and d['email']['1h']['e2']['sent'] == 3


def test_the_alert_member_with_no_subscription_counts_0(client, monkeypatch):
    monkeypatch.setenv('AHAVAH_ALERT_PUSH_PERSON_ID', '2147483000')
    assert _ok(client)['alert_member_push_subscriptions'] == 0


def test_the_alert_members_subscriptions_are_counted(client, make_person, monkeypatch):
    p = make_person(name='AlertOwner')
    with api_tx() as tx:
        for i in range(2):
            tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                          VALUES (%(p)s, %(e)s, 'k', 'a')""", dict(p=p['id'], e=f'https://push.test/{p["id"]}/{i}'))
    monkeypatch.setenv('AHAVAH_ALERT_PUSH_PERSON_ID', str(p['id']))
    assert _ok(client)['alert_member_push_subscriptions'] == 2


@pytest.mark.parametrize('until,mode', [('2999-01-01', 'shadow'), ('2020-01-01', 'enforce'), (None, 'enforce')])
def test_the_mode_and_shadow_date_are_reported(client, monkeypatch, until, mode):
    if until is None:
        monkeypatch.delenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', raising=False)
    else:
        monkeypatch.setenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', until)
    d = _ok(client)
    assert d['mode']['per_person'] == 'enforce' and d['mode']['global'] == mode
    assert d['mode']['global_shadow_until'] == until


def test_outbox_counts_by_state(client):
    d = _ok(client)
    assert set(d['outbox']) >= {'queued', 'accepted', 'failed', 'skipped'}


def test_no_field_carries_an_address(client, monkeypatch):
    import smtp as smtp_mod
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', lambda self, **kw: 'mid')
    m = smtp_mod.make_aws_smtp()
    for _ in range(4):
        m.send(subject='Hello', body='x', to_addr='private.person@gmail.com', kind='hello', retries=0)
    from service import sendguard
    monkeypatch.setattr('service.notifications._send_to_user_blocking', lambda *a, **k: 1)
    sendguard.tick()
    body = json.dumps(_ok(client))
    assert '@' not in body and 'private.person' not in body
