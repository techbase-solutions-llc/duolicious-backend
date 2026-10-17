"""When each week's quick question goes live (TEC-1845).

Owner decision 1 (16 Oct 2026): the question drops on the first free day of
each Sunday-to-Saturday week by the lunar rule in
service/spotlight/restdays.py, never a fixed Sunday, and the weekly push
goes at 18:00 the member's local time on that day.

A free day is not a rest day and not the eve of one: a rest period starts at
17:00 Barbados the evening before, and 18:00 anywhere in the Americas falls
after that. The day after a drop day must be known too, so the last
possible drop day is the day before KNOWN_THROUGH. A week with no free day
has no question.

The current question is the latest approved drop on or before today's
Barbados date, for at most CURRENT_FOR_DAYS: it stays on the card until the
next one goes live.

restdays is read as a module on every call, so a test can move its dates.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import service.spotlight.restdays as rd
from service.questions.bank import LIVE, question_json

CURRENT_FOR_DAYS = 14

# Owner decision 2 (16 Oct): the first 6 weeks, in order. Admin > Questions
# proposes them for empty weeks; the owner approves or reorders.
FIRST_WEEKS = ('mountains-or-sea', 'window-or-aisle', 'sabbath-afternoon',
               'early-or-late', 'host-or-dessert', 'people-or-quiet')


def barbados_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(rd.BARBADOS).date()


def week_start(day: date) -> date:
    """The Sunday that starts `day`'s week."""
    return day - timedelta(days=day.isoweekday() % 7)


def _free(day: date) -> bool:
    return day not in rd.REST_DAYS and (day + timedelta(days=1)) not in rd.REST_DAYS


def drop_day(week_of: date) -> Optional[date]:
    start = week_start(week_of)
    for i in range(7):
        day = start + timedelta(days=i)
        if day + timedelta(days=1) > rd.KNOWN_THROUGH:
            return None
        if _free(day):
            return day
    return None


def week_starts_at(live_on: date) -> datetime:
    """The start of a question week, for the 1-push-a-week budget."""
    return datetime.combine(live_on, time(0, 0), rd.BARBADOS)


def resting(now: datetime) -> bool:
    """Inside a rest period, or past the last date the calendar is read for:
    no question push and no launch email goes."""
    return rd.is_rest_period(now) or rd.is_beyond_known(now)


# The latest approved drop first, then whether its question is still live:
# switching this week's question off empties the card, it never brings back
# an older week's.
_Q_CURRENT = f"""
    SELECT d.live_on, b.key, b.text, b.format, b.options
      FROM (SELECT live_on, prompt_key FROM question_drop
             WHERE approved_at IS NOT NULL
               AND live_on <= %(today)s
               AND live_on > %(today)s::date - {CURRENT_FOR_DAYS}
             ORDER BY live_on DESC LIMIT 1) d
      JOIN prompt_bank b ON b.key = d.prompt_key AND {LIVE}
"""


def current_drop(tx, now: Optional[datetime] = None) -> Optional[dict]:
    row = tx.execute(_Q_CURRENT, dict(today=barbados_today(now))).fetchone()
    return dict(live_on=row['live_on'], question=question_json(row)) if row else None
