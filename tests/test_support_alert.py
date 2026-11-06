"""Support messages in the owner's daily alert (TEC-2115;
docs/plans/2026-11-05-support-messages-in-admin.md): an open message older
than 24 hours is counted and listed, a handled one or a younger one is not,
and none adds no line. Count only: never a subject, a body or an address.
Behind its own switch, support_alert, off until the owner has seen the
proof."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import admin_alerts
from service.cron import adminalerts

AFTER_SEVEN = datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc)  # 07:30 in Barbados
NOW = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)
POSTS = [dict(kind='brand', week=None, members=None,
              in_review_since=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc))]
LINE = re.compile(r'\d+ support messages? ha(s|ve) had no answer for more than 24 hours')


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
def messages():
    """Inserts rows by (status, hours ago); deletes them afterwards."""
    ids = []

    def add(status: str, hours: int) -> None:
        with api_tx() as tx:
            ids.append(tx.execute(
                """INSERT INTO support_message (gmail_message_id, gmail_thread_id, from_address,
                                                subject, body_text, received_at, status)
                   VALUES (%(g)s, %(g)s, 'secret-sender@example.com', 'Secret subject',
                           'Secret body', NOW() - make_interval(hours => %(h)s), %(s)s)
                   RETURNING id""",
                dict(g=f'test-{uuid4().hex}', h=hours, s=status)).fetchone()['id'])

    yield add
    with api_tx() as tx:
        tx.execute('DELETE FROM support_message WHERE id = ANY(%(i)s)', dict(i=ids))
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")


def _count() -> int:
    with api_tx('read committed') as tx:
        return adminalerts.open_support(tx)


def test_only_an_open_message_older_than_24_hours_counts(messages):
    before = _count()
    messages('open', 30)
    assert _count() == before + 1
    messages('handled', 30)
    messages('not_for_us', 30)
    messages('open', 2)
    assert _count() == before + 1


def test_the_line_reads_as_the_plan_words_it():
    assert admin_alerts.support_line(1) == '1 support message has had no answer for more than 24 hours'
    assert admin_alerts.support_line(3) == '3 support messages have had no answer for more than 24 hours'


def test_the_line_rides_in_the_post_alert_with_a_link_to_support():
    subject, html = admin_alerts.daily_email(POSTS, 2, NOW)
    assert subject == '1 post is waiting for approval'
    assert '2 support messages have had no answer for more than 24 hours' in html
    assert 'https://admin.ahavah.app/?tab=support' in html
    assert 'https://admin.ahavah.app/?tab=growth' in html
    assert '—' not in html
    assert '!' not in admin_alerts.support_line(2) and '—' not in admin_alerts.support_line(2)


def test_zero_adds_no_line():
    _, with_none = admin_alerts.daily_email(POSTS, 0, NOW)
    assert 'support message' not in with_none and '?tab=support' not in with_none
    assert admin_alerts.daily_email(POSTS, 0, NOW) == admin_alerts.stale_posts_email(POSTS, NOW)


def test_a_lone_support_line_is_the_alert(messages, smtp, monkeypatch):
    monkeypatch.setenv('AHAVAH_ADMIN_ALERTS_CRON_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_STALE_POST_ALERT_ENABLED', raising=False)
    monkeypatch.setenv('AHAVAH_SUPPORT_ALERT_ENABLED', '1')
    messages('open', 30)
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")
    adminalerts.tick(AFTER_SEVEN)
    adminalerts.tick(AFTER_SEVEN)
    assert len(smtp.sent) == 1
    mail = smtp.sent[0]
    assert LINE.fullmatch(mail['subject'])
    assert LINE.search(mail['body']) and 'https://admin.ahavah.app/?tab=support' in mail['body']
    for secret in ('Secret subject', 'Secret body', 'secret-sender@example.com'):
        assert secret not in mail['body'] and secret not in mail['subject']


def test_nothing_sends_while_the_support_switch_is_off(messages, smtp, monkeypatch):
    monkeypatch.setenv('AHAVAH_ADMIN_ALERTS_CRON_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_STALE_POST_ALERT_ENABLED', raising=False)
    monkeypatch.delenv('AHAVAH_SUPPORT_ALERT_ENABLED', raising=False)
    messages('open', 30)
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")
    adminalerts.tick(AFTER_SEVEN)
    assert smtp.sent == []


def test_no_open_message_sends_nothing(messages, smtp, monkeypatch):
    monkeypatch.setenv('AHAVAH_ADMIN_ALERTS_CRON_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_STALE_POST_ALERT_ENABLED', raising=False)
    monkeypatch.setenv('AHAVAH_SUPPORT_ALERT_ENABLED', '1')
    monkeypatch.setattr(adminalerts, 'open_support', lambda tx: 0)
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")
    assert adminalerts.tick(AFTER_SEVEN)['support'] == 0
    assert smtp.sent == []


def test_the_support_email_is_in_the_samples_and_the_proofs():
    from scripts import send_admin_alert_proofs as ap
    from tests.email_samples import SAMPLES
    row = next(s for s in SAMPLES if s['name'] == 'STAFF_support_alert')
    assert 'error' not in row and row['audience'] == 'staff'
    assert row['subject'] == '2 support messages have had no answer for more than 24 hours'
    assert 'support_alert' in [e['name'] for e in ap.plan()]
