"""The owner's rest days, as the scheduler reads them (TEC-945).

Every test passes its own clock and sets its own dates on the module, so
none of them depends on when the suite happens to run. The conftest's
autouse fixture empties the calendar for every other test in the suite;
these set it back to what they need.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd

BB = rd.BARBADOS


def _bb(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), BB)


@pytest.fixture
def one_sabbath(monkeypatch):
    """A single rest day, Saturday 3 October 2026, and a calendar read
    through the following Saturday."""
    monkeypatch.setattr(rd, 'REST_DAYS', (date(2026, 10, 3),))
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2026, 10, 10))
    return date(2026, 10, 3)


EARLY = datetime(2026, 9, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Where a rest period starts and ends
# ---------------------------------------------------------------------------

def test_the_rest_period_starts_at_17_barbados_the_evening_before(one_sabbath):
    eve = one_sabbath - timedelta(days=1)
    assert rd.is_rest_period(_bb(eve, 16, 59)) is False
    assert rd.is_rest_period(_bb(eve, 17, 0)) is True


def test_it_covers_the_whole_day_and_ends_at_midnight_barbados(one_sabbath):
    assert rd.is_rest_period(_bb(one_sabbath, 12)) is True
    assert rd.is_rest_period(_bb(one_sabbath, 23, 59)) is True
    assert rd.is_rest_period(_bb(one_sabbath + timedelta(days=1), 0, 0)) is False


def test_the_boundary_holds_when_the_clock_is_utc(one_sabbath):
    """The publisher's clock is UTC. 17:00 in Barbados is 21:00 UTC, and a
    comparison that forgot the zone would put the start four hours late."""
    eve = one_sabbath - timedelta(days=1)
    assert rd.is_rest_period(datetime.combine(eve, time(20, 59), timezone.utc)) is False
    assert rd.is_rest_period(datetime.combine(eve, time(21, 0), timezone.utc)) is True


def test_a_naive_datetime_is_refused_rather_than_guessed_at(one_sabbath):
    with pytest.raises(ValueError):
        rd.is_rest_period(datetime(2026, 10, 3, 12))


# ---------------------------------------------------------------------------
# Why a slot is refused
# ---------------------------------------------------------------------------

def test_a_slot_in_the_past_is_refused(one_sabbath):
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    assert rd.slot_problem(now - timedelta(minutes=1), now) == 'past'


def test_a_slot_inside_a_rest_period_is_refused(one_sabbath):
    assert rd.slot_problem(_bb(one_sabbath, 9), EARLY) == 'rest_day'
    assert rd.slot_problem(_bb(one_sabbath - timedelta(days=1), 18), EARLY) == 'rest_day'


def test_a_slot_past_the_known_calendar_is_unknown_not_free(one_sabbath):
    """The owner's calendar has not been read past KNOWN_THROUGH. The dates
    after it are not free, they are unknown, so they are refused."""
    assert rd.slot_problem(_bb(date(2026, 10, 11), 9), EARLY) == 'unknown'


def test_an_ordinary_slot_is_accepted(one_sabbath):
    assert rd.slot_problem(_bb(date(2026, 10, 1), 9), EARLY) is None


# ---------------------------------------------------------------------------
# Rolling forward
# ---------------------------------------------------------------------------

def test_the_next_valid_slot_skips_the_whole_rest_period(one_sabbath):
    """From Friday 2 October at 19:00 UTC, both of Friday's slots (12:00 and
    18:00 UTC) have gone and both of Saturday's fall on the Sabbath, so the
    first slot is Sunday 12:00 UTC."""
    now = datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc)
    assert rd.next_valid_slot(now) == datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_a_friday_afternoon_slot_is_still_before_the_eve(one_sabbath):
    """18:00 UTC is 14:00 in Barbados, three hours before the eve begins.
    Rolling forward must not throw away a Friday slot that is still fine."""
    now = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
    assert rd.next_valid_slot(now) == datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)


def test_the_next_valid_slot_is_today_when_today_is_fine(one_sabbath):
    now = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert rd.next_valid_slot(now) == datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def test_there_is_no_next_slot_once_the_known_calendar_runs_out(one_sabbath):
    now = datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)
    assert rd.next_valid_slot(now) is None


# ---------------------------------------------------------------------------
# The real dates, from the owner's calendar
# ---------------------------------------------------------------------------

@pytest.mark.real_calendar
def test_the_real_calendar_carries_the_owners_rest_days():
    """Read from docs/marketing/feast-dates-2026.md, which came from the
    owner's Biblical Calendar Engine account. The admin keeps the same list
    and ahavah-admin/tests/rest-days.test.mjs fails if the two drift."""
    for d in (date(2026, 9, 19), date(2026, 9, 21), date(2026, 9, 26),
              date(2026, 10, 3), date(2026, 10, 10)):
        assert d in rd.REST_DAYS
    assert rd.KNOWN_THROUGH == date(2026, 10, 10)
