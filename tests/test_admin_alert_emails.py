"""The owner's stale-post alert (TEC-1897; frame G.8): to the owner only, no
member named. Its proof goes to his address, never the outbox.

There is no second report email: the report email that already goes to
DUO_REPORT_EMAIL (antiabuse/lodgereport) is the report alert, and the
owner's "Email me when a report arrives" is its switch."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import admin_alerts
from scripts import send_admin_alert_proofs as ap

NOW = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)  # 07:00 in Barbados
POSTS = [
    dict(kind='roundup', week=41, members=4, in_review_since=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)),
    dict(kind='roundup', week=42, members=2, in_review_since=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)),
]


def test_the_stale_email_reads_as_the_design_draws_it():
    subject, html = admin_alerts.stale_posts_email(POSTS, NOW)
    assert subject == '2 posts are waiting for approval'
    for line in ('Admin alert · 14 Oct, 07:00 Barbados',
                 'Roundup, week 41, 4 members. In review since 5 Oct.',
                 'Roundup, week 42, 2 members. In review since 12 Oct.',
                 'Open the queue',
                 'Sent once a day while a post has waited more than 24 hours.'):
        assert line in html
    assert 'https://admin.ahavah.app/?tab=growth' in html
    assert '—' not in html  # no em dash


def test_one_post_and_other_kinds():
    one = [dict(kind='brand', week=None, members=None,
                in_review_since=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc))]
    subject, html = admin_alerts.stale_posts_email(one, NOW)
    assert subject == '1 post is waiting for approval'
    assert 'Brand post. In review since 12 Oct.' in html
    assert admin_alerts.post_line(dict(kind='roundup', week=40, members=1,
                                       in_review_since=NOW)) == 'Roundup, week 40, 1 member. In review since 14 Oct.'


def test_there_is_no_second_report_email():
    assert not hasattr(admin_alerts, 'report_email')


def test_the_alert_goes_to_the_proof_address():
    from scripts.send_proofs import PROOF_TO
    from service.admin.owner import OWNER_EMAILS
    assert admin_alerts.OWNER_TO == PROOF_TO == 'harrigan.tennyson@gmail.com'
    assert admin_alerts.OWNER_TO in OWNER_EMAILS


def test_the_email_is_in_the_samples():
    from tests.email_samples import SAMPLES
    row = next(s for s in SAMPLES if s['name'] == 'STAFF_stale_posts')
    assert 'error' not in row and row['audience'] == 'staff'


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def smtp(monkeypatch):
    s = _Smtp()
    monkeypatch.setattr(ap, '_smtp', lambda: s)
    return s


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                for t in ('email_outbox', 'email_send_log', 'admin_alert_log')}


def test_the_proof_plan_covers_the_stale_alert():
    assert [e['name'] for e in ap.plan()] == ['stale_post_alert']


def test_a_dry_run_sends_nothing(smtp, capsys):
    before = _counts()
    ap.main([])
    assert smtp.sent == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    before = _counts()
    ap.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == 1 and smtp.sent[0]['subject'].startswith('[PROOF] ')
    assert _counts() == before
