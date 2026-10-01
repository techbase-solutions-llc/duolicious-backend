"""The days Ahavah does not post, and the next moment it may.

THE SOURCE IS THE OWNER'S CALENDAR, NOT THE WEB.

Every date here comes from `docs/marketing/feast-dates-2026.md`, which was
read from the owner's own Biblical Calendar Engine account. The calendar is
lunar: weekly Sabbaths fall on lunar days 8, 15, 22 and 29, so they are not
fixed weekdays, and no web calendar or weekday rule can stand in for them.

The rule, from that file: no promotional posts and no campaign emails on the
Day of Atonement or on the Sabbaths. High holy days are not a ban, they get
warm community content only; that is a judgement about content, so it is
enforced where the content lives (the admin calendar), not here.

A REST DAY STARTS THE EVENING BEFORE.

Observance runs from the previous evening. Sunset in Barbados sits between
about 17:45 and 18:20 all year, so a rest period here runs from 17:00
Barbados time the evening before to midnight Barbados time at its end. The
hour of margin is deliberate: a post a few minutes into the Sabbath is the
failure this module exists to prevent, and a post an hour early costs
nothing.

NOTHING IS KNOWN AFTER `KNOWN_THROUGH`.

The owner's calendar has been read through the seventh month, and the
eighth is entered provisionally (see REST_DAYS). A date
past that is not "free", it is unknown, so `slot_problem` refuses it rather
than guessing. Extending this is one edit: add the next month's Sabbaths and
move `KNOWN_THROUGH`, after re-reading the engine.

`ahavah-admin/src/lib/rest-days.ts` carries the same dates for the calendar's
own tests, and `ahavah-admin/tests/rest-days.test.mjs` reads this file off
disk and fails if the two ever disagree. Change both, or neither.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

BARBADOS = ZoneInfo('America/Barbados')

# No posts at all. The Day of Atonement and the weekly Sabbaths, 2026, from
# the owner's calendar. Past dates stay listed: they cost nothing, and a
# test that walks the list is easier to trust with the whole year in it.
REST_DAYS: tuple[date, ...] = (
    date(2026, 9, 19),   # Sabbath
    date(2026, 9, 21),   # Day of Atonement
    date(2026, 9, 26),   # Sabbath, first day of Tabernacles
    date(2026, 10, 3),   # Sabbath, the Last Great Day
    date(2026, 10, 10),  # Sabbath
    # EIGHTH MONTH, PROVISIONAL (entered 2026-10-01, TEC-1447). The owner's
    # calendar holds no record for this month yet: its first day is 11 or 12
    # October depending on what the owner observes and confirms, so each
    # Sabbath (lunar days 8, 15, 22, 29) has two candidate dates. Both are
    # blocked, because posting on a Sabbath is the failure and losing a
    # Monday slot is only a cost. When the owner confirms the month, delete
    # the four dates that turn out not to be Sabbaths, here and in the admin.
    date(2026, 10, 18), date(2026, 10, 19),
    date(2026, 10, 25), date(2026, 10, 26),
    date(2026, 11, 1), date(2026, 11, 2),
    date(2026, 11, 8), date(2026, 11, 9),
)

# The last date the owner's calendar has been read for. Anything later is
# unknown, and a slot there is refused rather than assumed to be free.
KNOWN_THROUGH = date(2026, 11, 9)

# How long before a rest day's date its observance starts, in Barbados time.
_EVE = time(17, 0)


def _rest_window(day: date) -> tuple[datetime, datetime]:
    """[start, end) of one rest period, as aware datetimes."""
    start = datetime.combine(day - timedelta(days=1), _EVE, BARBADOS)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), BARBADOS)
    return start, end


def is_rest_period(at: datetime) -> bool:
    if at.tzinfo is None:
        raise ValueError('naive datetime')
    return any(start <= at < end for start, end in map(_rest_window, REST_DAYS))


def is_beyond_known(at: datetime) -> bool:
    """After the last date the owner's calendar has been read for."""
    if at.tzinfo is None:
        raise ValueError('naive datetime')
    return at.astimezone(BARBADOS).date() > KNOWN_THROUGH


def slot_problem(at: datetime, now: Optional[datetime] = None) -> Optional[str]:
    """Why a post may not go out at `at`, or None if it may.

    'past'     the slot has already gone; publishing it now would put it out
               at whatever moment the approval happened to land.
    'rest_day' inside a rest period, evening before included.
    'unknown'  after KNOWN_THROUGH, where nobody has read the calendar yet.
    """
    if at.tzinfo is None:
        raise ValueError('naive datetime')
    now = now or datetime.now(timezone.utc)
    if at <= now:
        return 'past'
    if is_beyond_known(at):
        return 'unknown'
    if is_rest_period(at):
        return 'rest_day'
    return None


def next_valid_slot(now: Optional[datetime] = None) -> Optional[datetime]:
    """The first of 12:00 or 18:00 UTC, today or later, that `slot_problem`
    accepts. None when every candidate up to KNOWN_THROUGH is refused, which
    means the calendar needs re-reading before anything else can be
    scheduled.

    12:00 and 18:00 UTC are the two slots `_default_slot` already uses for
    member cards (08:00 and 14:00 in Barbados), so a brand post that rolls
    forward lands where the rest of the feed does.
    """
    now = now or datetime.now(timezone.utc)
    day = now.date()
    last = KNOWN_THROUGH + timedelta(days=1)
    while day <= last:
        for hour in (12, 18):
            slot = datetime.combine(day, time(hour, 0), timezone.utc)
            if slot_problem(slot, now) is None:
                return slot
        day += timedelta(days=1)
    return None
