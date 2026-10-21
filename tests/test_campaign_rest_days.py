"""Campaign emails keep the owner's rest days (TEC-1845 admin audit, Medium).

restdays.py states the rule: no campaign emails on the Day of Atonement or
on the Sabbaths. Nothing in service/campaigns read it, so the Send button
and the weekly e2 cron could mail members during a rest period.

The Send route refuses a real send with 409 rest_day; a dry run still runs,
because it sends nothing. The e2 cron skips a tick inside a rest period.
Both ask schedule.campaign_rest_now. conftest empties the rest-day
calendar for every test, so the other send tests do not depend on the day
they run; the rule test below reads the real calendar."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import api_tx


@pytest.mark.real_calendar
def test_the_rule_reads_the_owners_calendar():
    from service.campaigns import schedule
    # 26 Oct 2026, a provisional Sabbath, at 12:00 UTC (08:00 Barbados).
    assert schedule.is_campaign_rest_period(datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
    # 21 Oct 2026, an ordinary Wednesday.
    assert not schedule.is_campaign_rest_period(datetime(2026, 10, 21, 12, tzinfo=timezone.utc))


def test_a_real_send_is_refused_in_a_rest_period(client, admin_headers, monkeypatch):
    from service.campaigns import schedule
    import service.campaigns.runner as runner
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: True)
    called = []
    monkeypatch.setattr(runner, 'run_campaign', lambda *a, **k: called.append(1))
    r = client.post('/admin/growth/emails/e2/send', headers=admin_headers,
                    json=dict(campaign_id='rest-test', dry_run=False))
    assert r.status_code == 409
    assert r.get_json()['error'] == 'rest_day'
    assert called == []


def test_a_dry_run_still_runs_in_a_rest_period(client, admin_headers, monkeypatch):
    from service.campaigns import schedule
    import service.campaigns.runner as runner
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: True)
    monkeypatch.setattr(runner, 'run_campaign', lambda *a, **k: dict(
        campaign_id='rest-dry', dry_run=True, queued=0, built=0,
        skipped=0, error=None))
    try:
        r = client.post('/admin/growth/emails/e2/send', headers=admin_headers,
                        json=dict(campaign_id='rest-dry', dry_run=True))
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM admin_audit_log WHERE metadata->>'campaign_id' = 'rest-dry'")


def test_the_weekly_cron_skips_a_rest_period(monkeypatch):
    import service.cron.communityweekly as cron
    from service.campaigns import schedule
    monkeypatch.setattr(cron, 'is_send_window', lambda now: True)
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: True)
    called = []
    monkeypatch.setattr(cron, 'run_campaign', lambda *a, **k: called.append(1))
    cron._send_once()
    assert called == []
