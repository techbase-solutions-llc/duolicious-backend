"""The adminalerts cron (TEC-1897): the daily stale-post alert to the owner,
behind the cron's own switch and the alert's, sent once a day; and the
retention of the error tally and the online days. There are no report
alerts here: the report email is antiabuse/lodgereport's."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service.cron import adminalerts

# 14 Oct 2026: 11:30 UTC is 07:30 in Barbados; 10:30 UTC is 06:30.
AFTER_SEVEN = datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc)
BEFORE_SEVEN = datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc)


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'id'


@pytest.fixture
def smtp(monkeypatch):
    s = _Smtp()
    monkeypatch.setattr(adminalerts, '_smtp', lambda: s)
    return s


@pytest.fixture
def stale_roundup():
    key = f'roundup:2026-W41-{uuid4().hex[:6]}'
    with api_tx() as tx:
        for platform in ('facebook', 'instagram'):
            tx.execute(
                """INSERT INTO publishing_queue (request_key, kind, platform, status, created_at, payload)
                   VALUES (%(k)s, 'roundup', %(p)s, 'review', NOW() - INTERVAL '3 days',
                           '{"count": 4}'::jsonb)""", dict(k=key, p=platform))
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")
    yield key
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(k)s", dict(k=key))
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")


@pytest.fixture
def cron_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_ADMIN_ALERTS_CRON_ENABLED', '1')


def test_nothing_sends_while_the_switch_is_off(smtp, stale_roundup, cron_on, monkeypatch):
    monkeypatch.delenv('AHAVAH_STALE_POST_ALERT_ENABLED', raising=False)
    adminalerts.tick(AFTER_SEVEN)
    assert smtp.sent == []


def test_the_cron_does_nothing_while_its_own_switch_is_off(smtp, stale_roundup, make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_ADMIN_ALERTS_CRON_ENABLED', raising=False)
    monkeypatch.setenv('AHAVAH_STALE_POST_ALERT_ENABLED', '1')
    p = make_person(name='KeepMe')
    with api_tx() as tx:
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(i)s, CURRENT_DATE - 200, NOW() - INTERVAL '200 days', NOW() - INTERVAL '200 days')""",
                   dict(i=p['id']))
    assert adminalerts.tick(AFTER_SEVEN) == {'off': True}
    assert smtp.sent == []
    with api_tx('read committed') as tx:
        left = tx.execute('SELECT count(*) AS n FROM member_online_day WHERE person_id = %(i)s',
                          dict(i=p['id'])).fetchone()['n']
    assert left == 1


def test_the_stale_alert_goes_once_a_day_after_seven(smtp, stale_roundup, cron_on, monkeypatch):
    monkeypatch.setenv('AHAVAH_STALE_POST_ALERT_ENABLED', '1')
    adminalerts.tick(BEFORE_SEVEN)
    assert smtp.sent == []
    adminalerts.tick(AFTER_SEVEN)
    adminalerts.tick(AFTER_SEVEN)
    assert len(smtp.sent) == 1
    mail = smtp.sent[0]
    assert mail['to_addr'] == 'harrigan.tennyson@gmail.com'
    assert 'Roundup, week 41, 4 members. In review since' in mail['body']
    with api_tx('read committed') as tx:
        audit = tx.execute("""SELECT metadata FROM admin_audit_log WHERE action = 'admin_alert.sent'
                               ORDER BY created_at DESC LIMIT 1""").fetchone()['metadata']
    assert audit['alert'] == 'stale_posts'


def test_a_post_under_24_hours_is_not_stale(smtp, monkeypatch):
    monkeypatch.setenv('AHAVAH_STALE_POST_ALERT_ENABLED', '1')
    key = f'roundup:2026-W42-{uuid4().hex[:6]}'
    with api_tx() as tx:
        tx.execute("""INSERT INTO publishing_queue (request_key, kind, platform, status)
                      VALUES (%(k)s, 'roundup', 'facebook', 'review')""", dict(k=key))
        posts = adminalerts.stale_posts(tx)
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(k)s", dict(k=key))
    assert all(p['request_key'] != key for p in posts)


def test_old_rows_are_pruned(make_person):
    p = make_person(name='PruneMe')
    with api_tx() as tx:
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(i)s, CURRENT_DATE - 200, NOW() - INTERVAL '200 days', NOW() - INTERVAL '200 days')""",
                   dict(i=p['id']))
        tx.execute("""INSERT INTO api_error_tally (route, hour, n, last_at)
                      VALUES ('/prune-me', date_trunc('hour', NOW() - INTERVAL '40 days'), 1, NOW() - INTERVAL '40 days')
                      ON CONFLICT DO NOTHING""")
        adminalerts.prune(tx)
        left = tx.execute("""SELECT (SELECT count(*) FROM member_online_day WHERE person_id = %(i)s) AS days,
                                    (SELECT count(*) FROM api_error_tally WHERE route = '/prune-me') AS errs""",
                          dict(i=p['id'])).fetchone()
    assert dict(left) == dict(days=0, errs=0)
