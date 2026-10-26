"""The weekly email moves to the next free day (TEC-1933).

26 Oct 2026 plan, section 2. Each ISO week has a nominal slot, its send
weekday at the send hour (Monday 12:00 UTC). When that slot is in one of the
owner's rest periods or past KNOWN_THROUGH, the week's slot moves forward a
day at a time, same hour, until it is free, and never past that week's
Sunday. A week with no free day has no slot.

A slide happens only when the nominal slot itself is refused. A free Monday
that has already passed must never turn into a Tuesday send: the change
deploys after Monday 26 Oct's window has closed, and the owner wants the
first weekly email on Monday 2 Nov, not on Tuesday 27 Oct.

Most tests pin the calendar on the restdays module; the real_calendar ones
read the dates as the owner confirmed them.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from service.campaigns import schedule
from service.campaigns.schedule import is_send_window, next_send_at, week_slot
from service.campaigns.weekid import week_campaign_id


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def _calendar(monkeypatch, rest, known_through='2027-01-31'):
    monkeypatch.setattr(rd, 'REST_DAYS', tuple(date.fromisoformat(d) for d in rest))
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.fromisoformat(known_through))


# Monday 26 Oct 2026 to Sunday 1 Nov 2026 is one ISO week.
WEEK = [f'2026-10-{d}' for d in range(26, 32)] + ['2026-11-01']


# ---------------------------------------------------------------------------
# The week's slot
# ---------------------------------------------------------------------------

def test_a_free_monday_is_the_slot(monkeypatch):
    _calendar(monkeypatch, [])
    for day in range(26, 32):
        assert week_slot(_utc(2026, 10, day, 3)) == _utc(2026, 10, 26, 12)


def test_a_rest_day_monday_slides_to_tuesday(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    assert week_slot(_utc(2026, 10, 28, 9)) == _utc(2026, 10, 27, 12)


def test_it_keeps_sliding_while_each_day_is_refused(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26', '2026-10-27'])
    assert week_slot(_utc(2026, 10, 26, 9)) == _utc(2026, 10, 28, 12)


def test_the_eve_of_a_rest_day_does_not_slide_a_noon_slot(monkeypatch):
    # The rest period for Tuesday starts at 21:00 UTC on Monday, so Monday
    # 12:00 UTC is free. The second belt in the cron holds the evening.
    _calendar(monkeypatch, ['2026-10-27'])
    assert week_slot(_utc(2026, 10, 26, 9)) == _utc(2026, 10, 26, 12)


def test_a_slide_never_leaves_the_iso_week(monkeypatch):
    _calendar(monkeypatch, WEEK[:-1])
    assert week_slot(_utc(2026, 10, 26, 9)) == _utc(2026, 11, 1, 12)
    _calendar(monkeypatch, WEEK)
    assert week_slot(_utc(2026, 10, 26, 9)) is None


def test_a_week_past_the_known_calendar_has_no_slot(monkeypatch):
    _calendar(monkeypatch, [], '2026-10-25')
    assert week_slot(_utc(2026, 10, 26, 9)) is None


def test_a_slide_stops_where_the_known_calendar_ends(monkeypatch):
    # Monday is a rest day and the calendar ends on Monday, so Tuesday is
    # unknown, not free.
    _calendar(monkeypatch, ['2026-10-26'], '2026-10-26')
    assert week_slot(_utc(2026, 10, 26, 9)) is None


def test_the_slot_reads_the_rest_rules_through_the_schedule_module(monkeypatch):
    _calendar(monkeypatch, [])
    monkeypatch.setattr(schedule, 'is_campaign_rest_period',
                        lambda at: at.date() == date(2026, 10, 26))
    assert week_slot(_utc(2026, 10, 26, 9)) == _utc(2026, 10, 27, 12)
    monkeypatch.setattr(schedule, 'is_campaign_rest_period', lambda at: False)
    monkeypatch.setattr(schedule, 'is_campaign_beyond_known', lambda at: True)
    assert week_slot(_utc(2026, 10, 26, 9)) is None


# ---------------------------------------------------------------------------
# The send window follows the slot
# ---------------------------------------------------------------------------

def test_a_slid_window_runs_from_the_slot_to_midnight(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    assert is_send_window(_utc(2026, 10, 26, 12)) is False
    assert is_send_window(_utc(2026, 10, 27, 11, 59)) is False
    assert is_send_window(_utc(2026, 10, 27, 12)) is True
    assert is_send_window(_utc(2026, 10, 27, 23, 59)) is True
    assert is_send_window(_utc(2026, 10, 28, 12)) is False


def test_a_free_monday_that_has_passed_does_not_slide(monkeypatch):
    _calendar(monkeypatch, [])
    assert is_send_window(_utc(2026, 10, 26, 13)) is True
    for day in range(27, 32):
        for hour in range(24):
            assert is_send_window(_utc(2026, 10, day, hour)) is False, (day, hour)


def test_a_week_with_no_free_day_has_no_window(monkeypatch):
    _calendar(monkeypatch, WEEK)
    for day in range(26, 32):
        for hour in range(24):
            assert is_send_window(_utc(2026, 10, day, hour)) is False, (day, hour)


@pytest.mark.real_calendar
def test_deploy_day_tuesday_27_october_is_not_a_send_window():
    # Monday 26 Oct is free under the confirmed calendar and its window has
    # passed by deploy time. Tuesday must not pick the week up.
    assert is_send_window(_utc(2026, 10, 26, 13)) is True
    for hour in range(24):
        assert is_send_window(_utc(2026, 10, 27, hour)) is False, hour
    assert is_send_window(_utc(2026, 10, 27, 13)) is False


@pytest.mark.real_calendar
def test_every_week_to_the_end_of_the_known_calendar_sends_on_monday():
    # No Monday from 26 Oct to 7 Dec is a Sabbath under the confirmed
    # calendar, so nothing slides; 14 Dec is past KNOWN_THROUGH.
    monday = _utc(2026, 10, 26, 12)
    while monday.date() <= date(2026, 12, 7):
        assert week_slot(monday) == monday, monday
        monday += timedelta(days=7)
    assert week_slot(_utc(2026, 12, 14, 12)) is None


# ---------------------------------------------------------------------------
# next_send_at, which Growth > Emails prints
# ---------------------------------------------------------------------------

def test_next_send_at_names_the_slid_slot(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    assert next_send_at(_utc(2026, 10, 23, 9)) == _utc(2026, 10, 27, 12)
    assert next_send_at(_utc(2026, 10, 26, 13)) == _utc(2026, 10, 27, 12)


def test_inside_a_slid_window_the_next_send_is_next_week(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    assert next_send_at(_utc(2026, 10, 27, 13)) == _utc(2026, 11, 2, 12)


def test_next_send_at_steps_over_a_week_with_no_free_day(monkeypatch):
    _calendar(monkeypatch, WEEK)
    assert next_send_at(_utc(2026, 10, 23, 9)) == _utc(2026, 11, 2, 12)


def test_next_send_at_is_none_once_the_known_calendar_runs_out(monkeypatch):
    _calendar(monkeypatch, [], '2026-10-25')
    assert next_send_at(_utc(2026, 10, 23, 9)) is None


@pytest.mark.real_calendar
def test_after_deploy_the_next_send_is_monday_2_november():
    assert next_send_at(_utc(2026, 10, 27, 0, 30)) == _utc(2026, 11, 2, 12)


@pytest.mark.real_calendar
def test_the_last_send_before_the_calendar_runs_out():
    assert next_send_at(_utc(2026, 12, 1, 9)) == _utc(2026, 12, 7, 12)
    assert next_send_at(_utc(2026, 12, 7, 13)) is None


def test_the_window_and_the_next_slot_never_both_point_at_now(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26', '2026-10-27'])
    for day in range(26, 32):
        for hour in range(24):
            now = _utc(2026, 10, day, hour)
            nxt = next_send_at(now)
            assert nxt is not None and nxt > now, (now, nxt)


# ---------------------------------------------------------------------------
# The cron sends inside a slid window, and only there
# ---------------------------------------------------------------------------

def _clock(monkeypatch, now):
    """Fix datetime.now in the cron and in the schedule module, which
    campaign_rest_now and campaign_beyond_known_now read."""
    import service.cron.communityweekly as cron

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(cron, 'datetime', _Fixed)
    monkeypatch.setattr(schedule, 'datetime', _Fixed)


def _cron_calls(monkeypatch, now):
    import service.cron.communityweekly as cron
    _clock(monkeypatch, now)
    calls = []
    monkeypatch.setattr(cron, 'recipients', lambda: [])
    monkeypatch.setattr(cron, 'run_campaign', lambda tx, campaign, cid, *a, **k: (
        calls.append((campaign, cid)) or dict(queued=0, error=None)))
    cron._send_once()
    return calls


def test_the_cron_sends_in_a_slid_window(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    now = _utc(2026, 10, 27, 13)
    assert _cron_calls(monkeypatch, now) == [('e2', week_campaign_id(now, 'e2'))]


def test_the_slid_send_keeps_the_weeks_campaign_id(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    [(_, cid)] = _cron_calls(monkeypatch, _utc(2026, 10, 27, 13))
    assert cid == week_campaign_id(_utc(2026, 10, 26, 12), 'e2')


def test_the_cron_sends_nothing_outside_a_slid_window(monkeypatch):
    _calendar(monkeypatch, ['2026-10-26'])
    for now in (_utc(2026, 10, 26, 13), _utc(2026, 10, 27, 11), _utc(2026, 10, 28, 13)):
        assert _cron_calls(monkeypatch, now) == [], now


def test_the_rest_check_still_holds_the_evening_of_the_slot(monkeypatch):
    # Tuesday is a rest day, so its period starts Monday 21:00 UTC (17:00
    # Barbados). Monday's slot is free, but a tick at 22:00 must not send.
    _calendar(monkeypatch, ['2026-10-27'])
    assert _cron_calls(monkeypatch, _utc(2026, 10, 26, 20)) != []
    assert _cron_calls(monkeypatch, _utc(2026, 10, 26, 22)) == []


@pytest.mark.real_calendar
def test_the_cron_sends_on_2_november_and_not_on_tuesday_27_october(monkeypatch):
    assert _cron_calls(monkeypatch, _utc(2026, 10, 27, 13)) == []
    assert _cron_calls(monkeypatch, _utc(2026, 11, 2, 13)) == [
        ('e2', week_campaign_id(_utc(2026, 11, 2, 13), 'e2'))]
