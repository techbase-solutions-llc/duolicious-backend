"""When the weekly community email is due, and whether anything will send it.

This lives in a leaf module because two very different callers need the same
few settings: the cron that does the sending, and the Growth > Emails route
that has to tell an operator when the next one goes out. Importing the cron
package from an API route would pull the runner, the templates and the
database helpers in behind it for the sake of three integers. Same reasoning,
and the same shape, as `service/verificationlease.py`.

THE SCHEDULE IS A WINDOW, NOT AN INSTANT.

A poll never wakes exactly on the hour and a container restart can skip an
instant entirely, so the cron sends at any point on the slot's day from the
send hour onward. What stops a second send is not the clock but the week's
campaign id (`service.campaigns.weekid`) meeting the runner's per-run dedupe.

Monday 12:00 UTC is 08:00 in Barbados, the same slot the member of the week
cards are scheduled into.

A REST DAY MOVES THE WEEK'S SLOT, IT DOES NOT CANCEL THE WEEK.

Each ISO week has a nominal slot, SEND_WEEKDAY at SEND_HOUR_UTC. When that
slot falls in one of the owner's rest periods or past KNOWN_THROUGH, the
slot moves forward a day at a time, same hour, to the first free one, and
never past that week's Sunday, so the week's campaign id still fits (26 Oct
2026 plan, TEC-1933). A week with no free day has no slot and is skipped.

Only a refused nominal slot moves. A free Monday that has already passed
stays where it was: the window is that Monday's, and it does not reopen on
Tuesday.

It is OFF by default. A deploy that starts mailing the whole membership on
its own is not something anybody asked for, so the owner turns it on once,
deliberately, with DUO_CRON_COMMUNITY_WEEKLY_ENABLED=1.
"""
from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional


_TRUE = frozenset({'1', 'true', 'yes', 'on'})
_FALSE = frozenset({'', '0', 'false', 'no', 'off'})


def _env_flag(name: str) -> bool:
    """The on switch, spelled any of the obvious ways.

    An operator turning this on will reach for `true` or `yes` as readily as
    `1`, and a flag that reads an unrecognised value as off fails in the
    worst possible direction: the log line is identical to a correct dormant
    deploy, so you believe you enabled a thing you did not. Anything we do
    not recognise raises at import instead, which stops the container and is
    impossible to miss.
    """
    raw = os.environ.get(name, '').strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(
        f"{name}={raw!r} is not a yes or a no. Use one of "
        f"{sorted(_TRUE)} or {sorted(_FALSE)}.")


def _env_int(name: str, default: int, *, low: int, high: int) -> int:
    """Unset or blank reads as the default, because compose files pass every
    setting through as an empty string when it is not configured.

    Out of range raises rather than clamping. `SEND_HOUR_UTC=25` would
    otherwise reach `datetime.replace(hour=25)` inside the Growth > Emails
    route and take the whole tab down with a 500, and `SEND_WEEKDAY=0` would
    give a window that can never open beside a next-send date the dashboard
    prints forever.
    """
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name}={raw!r} is not a whole number.") from None
    if not low <= value <= high:
        raise ValueError(f"{name}={value} is outside {low} to {high}.")
    return value


# ISO weekday: 1 is Monday, 7 is Sunday. isoweekday() never returns 0, so 0
# here would be a window that can never open.
SEND_WEEKDAY = _env_int('DUO_CRON_COMMUNITY_WEEKLY_WEEKDAY', 1, low=1, high=7)
SEND_HOUR_UTC = _env_int('DUO_CRON_COMMUNITY_WEEKLY_HOUR_UTC', 12, low=0, high=23)
COMMUNITY_WEEKLY_ENABLED = _env_flag('DUO_CRON_COMMUNITY_WEEKLY_ENABLED')


def _week_monday(at: datetime) -> datetime:
    """Midnight UTC on the Monday of `at`'s ISO week."""
    day = at.astimezone(timezone.utc).date()
    day -= timedelta(days=day.isoweekday() - 1)
    return datetime.combine(day, time(0, 0), timezone.utc)


def _nominal_slot(at: datetime) -> datetime:
    return _week_monday(at) + timedelta(days=SEND_WEEKDAY - 1, hours=SEND_HOUR_UTC)


def week_slot(at: datetime) -> Optional[datetime]:
    """The send slot of `at`'s ISO week, or None when the week has none.

    The nominal slot if it is free, else the first free day after it at the
    same hour, up to that week's Sunday. Free means outside a rest period
    and not past KNOWN_THROUGH, read through this module so a test can pin
    either rule. It depends only on the week, never on the time of `at`, so
    a free Monday that has passed is still the week's slot and nothing
    slides to the Tuesday after it.
    """
    nominal = _nominal_slot(at)
    # SEND_WEEKDAY up to Sunday (7), inclusive.
    for ahead in range(8 - SEND_WEEKDAY):
        slot = nominal + timedelta(days=ahead)
        if not (is_campaign_rest_period(slot) or is_campaign_beyond_known(slot)):
            return slot
    return None


def is_send_window(now: datetime) -> bool:
    """The week's slot (slid past rest days), from the send hour to midnight
    UTC that day."""
    slot = week_slot(now)
    if slot is None:
        return False
    return slot.date() == now.astimezone(timezone.utc).date() and now >= slot


# How far next_send_at looks before giving up. Ten years of weeks; the known
# calendar ends long before that, and the scan stops there.
_SCAN_WEEKS = 520


def next_send_at(now: datetime) -> Optional[datetime]:
    """The next slot strictly after `now`, slid past rest days, or None when
    no week before the end of the known calendar has one (the cron holds).

    Inside the window this returns NEXT week's slot, not this one, because
    inside the window the send has either already happened or is about to on
    the current tick. An operator reading "next send in 4 hours" while the
    email is going out right now would be worse than useless.
    """
    week = _week_monday(now)
    for _ in range(_SCAN_WEEKS):
        slot = week_slot(week)
        if slot is not None and slot > now:
            return slot
        if slot is None and is_campaign_beyond_known(_nominal_slot(week)):
            # KNOWN_THROUGH only moves forward in time, so no later week
            # can be known either.
            return None
        week += timedelta(days=7)
    return None


# THE OWNER'S REST DAYS (TEC-1845 admin audit).
#
# restdays.py states the rule: no campaign emails on the Day of Atonement or
# on the Sabbaths, which are lunar and fall on Mondays as often as any other
# day. Nothing here read it, so the weekly e2 and the Send button could mail
# the membership during a rest period. Both ask campaign_rest_now, and read
# it through this module (schedule.campaign_rest_now) so a test can pin it.
# week_slot reads the two rules below through this module for the same
# reason.

def is_campaign_rest_period(at: datetime) -> bool:
    """True inside a rest period, evening before included (restdays.py)."""
    from service.spotlight.restdays import is_rest_period
    return is_rest_period(at)


def campaign_rest_now() -> bool:
    return is_campaign_rest_period(datetime.now(timezone.utc))


# After KNOWN_THROUGH nobody has read the owner's calendar, so a day there
# may be a rest day. The weekly e2 cron holds until the calendar is extended
# rather than assume the day is free (23 Oct 2026, when the owner asked for
# the schedule to be switched on and its next Mondays fell past 9 Nov).

def is_campaign_beyond_known(at: datetime) -> bool:
    """True after the last date the owner's calendar has been read for."""
    from service.spotlight.restdays import is_beyond_known
    return is_beyond_known(at)


def campaign_beyond_known_now() -> bool:
    return is_campaign_beyond_known(datetime.now(timezone.utc))
