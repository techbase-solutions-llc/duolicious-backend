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


@pytest.mark.real_calendar
def test_a_day_beyond_the_known_calendar_counts_as_unknown():
    # 16 Nov 2026 is after KNOWN_THROUGH (9 Nov): nobody has read the
    # owner's calendar for it, so the weekly email must not assume it is free.
    from service.campaigns import schedule
    assert schedule.is_campaign_beyond_known(datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    assert not schedule.is_campaign_beyond_known(datetime(2026, 10, 21, 12, tzinfo=timezone.utc))


def test_the_weekly_cron_holds_beyond_the_known_calendar(monkeypatch):
    import service.cron.communityweekly as cron
    from service.campaigns import schedule
    monkeypatch.setattr(cron, 'is_send_window', lambda now: True)
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(schedule, 'campaign_beyond_known_now', lambda: True)
    called = []
    monkeypatch.setattr(cron, 'run_campaign', lambda *a, **k: called.append(1))
    cron._send_once()
    assert called == []


# ---------------------------------------------------------------------------
# The Send button and the Growth > Emails schedule keep the same hold as the
# cron (23 Oct 2026 review, LT-2 and E2-SENDBUTTON). Past KNOWN_THROUGH the
# cron holds e2, so a by-hand send must not go out on that unchecked day, and
# the row must not promise a Monday the cron will skip.
# ---------------------------------------------------------------------------

def test_a_real_send_is_refused_past_the_known_calendar(client, admin_headers, monkeypatch):
    from service.campaigns import schedule
    import service.campaigns.runner as runner
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(schedule, 'campaign_beyond_known_now', lambda: True)
    called = []
    monkeypatch.setattr(runner, 'run_campaign', lambda *a, **k: called.append(1))
    r = client.post('/admin/growth/emails/e2/send', headers=admin_headers,
                    json=dict(campaign_id='unknown-test', dry_run=False))
    assert r.status_code == 409
    assert r.get_json()['error'] == 'unknown'
    assert called == []


def test_a_dry_run_still_runs_past_the_known_calendar(client, admin_headers, monkeypatch):
    from service.campaigns import schedule
    import service.campaigns.runner as runner
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(schedule, 'campaign_beyond_known_now', lambda: True)
    monkeypatch.setattr(runner, 'run_campaign', lambda *a, **k: dict(
        campaign_id='unknown-dry', dry_run=True, queued=0, built=0,
        skipped=0, error=None))
    try:
        r = client.post('/admin/growth/emails/e2/send', headers=admin_headers,
                        json=dict(campaign_id='unknown-dry', dry_run=True))
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM admin_audit_log WHERE metadata->>'campaign_id' = 'unknown-dry'")


def _calendar(monkeypatch, rest, known_through):
    from datetime import date
    import service.spotlight.restdays as rd
    monkeypatch.setattr(rd, 'REST_DAYS', tuple(date.fromisoformat(d) for d in rest))
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.fromisoformat(known_through))


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_the_schedule_skips_a_rest_day_monday(monkeypatch):
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr, 'COMMUNITY_WEEKLY_ENABLED', True)
    _calendar(monkeypatch, ['2026-10-26'], '2027-01-31')
    s = gr._schedule_for('e2', _utc(2026, 10, 23, 9), _utc(2026, 10, 19, 12))
    assert s['next_send_at'] == _utc(2026, 11, 2, 12).isoformat()
    assert s['held'] is False


def test_the_schedule_is_held_past_the_known_calendar(monkeypatch):
    # 23 Oct 2026: 26 Oct, 2 Nov and 9 Nov are rest days and 16 Nov is past
    # KNOWN_THROUGH, so the cron sends nothing until the calendar is extended.
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr, 'COMMUNITY_WEEKLY_ENABLED', True)
    _calendar(monkeypatch, ['2026-10-26', '2026-11-02', '2026-11-09'], '2026-11-09')
    s = gr._schedule_for('e2', _utc(2026, 10, 23, 9), _utc(2026, 10, 19, 12))
    assert s['held'] is True
    assert s['next_send_at'] is None
    assert s['overdue'] is False


def test_a_week_skipped_for_a_rest_day_is_not_overdue(monkeypatch):
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr, 'COMMUNITY_WEEKLY_ENABLED', True)
    _calendar(monkeypatch, ['2026-10-26'], '2027-01-31')
    s = gr._schedule_for('e2', _utc(2026, 10, 28, 9), _utc(2026, 10, 19, 12))
    assert s['overdue'] is False


def test_a_held_week_is_not_called_missed(monkeypatch):
    # From 17 Nov the last send (19 Oct) is four weeks old, but every Monday
    # since was a rest day or held. Nothing was missed; the row says held.
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr, 'COMMUNITY_WEEKLY_ENABLED', True)
    _calendar(monkeypatch, ['2026-10-26', '2026-11-02', '2026-11-09'], '2026-11-09')
    s = gr._schedule_for('e2', _utc(2026, 11, 17, 9), _utc(2026, 10, 19, 12))
    assert s['held'] is True
    assert s['overdue'] is False


def test_a_free_monday_that_went_unsent_is_still_overdue(monkeypatch):
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr, 'COMMUNITY_WEEKLY_ENABLED', True)
    _calendar(monkeypatch, ['2026-10-26'], '2027-01-31')
    s = gr._schedule_for('e2', _utc(2026, 11, 3, 13), _utc(2026, 10, 19, 12))
    assert s['overdue'] is True
