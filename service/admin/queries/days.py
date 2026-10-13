"""Calendar days on the admin dashboard are BARBADOS days.

The dashboard is read in Barbados. The database session runs in UTC, so
`CURRENT_DATE` and `::date` give the UTC day, and after 20:00 in Barbados
the UTC date is already tomorrow: a member who joins at 21:30 lands on the
next day's number, and a series bounded by CURRENT_DATE ends a day ahead of
the dashboard's own sense of today. On 13 Oct 2026 at 08:56 Barbados the
Overview (which already used Barbados days) said 1 sign-up today and the
System tab said 3, because two members had joined the evening before.

Every tab now takes its days from here. The conversion belongs on BOTH
sides of a comparison, the series bounds and the per-row day; one without
the other is an off-by-one that only shows near midnight.

Durations stay in UTC. "Last 7 days", retention windows and expiry
arithmetic are lengths of time, not calendar days, and a time zone would be
wrong there.
"""

BARBADOS_TODAY = "(NOW() AT TIME ZONE 'America/Barbados')::date"


def barbados_day(column: str) -> str:
    """The Barbados day of a `timestamptz` column (waitlist_signup,
    beta_signup, referral, referral_link_click, token_ledger,
    entitlement_event)."""
    return f"({column} AT TIME ZONE 'America/Barbados')::date"


def barbados_day_of_naive_utc(column: str) -> str:
    """The Barbados day of a `timestamp WITHOUT time zone` column that holds
    UTC, which is what `person.sign_up_time` is.

    The DOUBLE conversion is not redundant. On a naive column,
    `AT TIME ZONE 'America/Barbados'` READS the value as Barbados local,
    which is backwards: the column stores UTC. `AT TIME ZONE 'UTC'` first
    marks it as UTC, and only then does the second conversion mean what it
    says. Getting this wrong puts every evening sign-up on the wrong day in
    the direction that looks plausible."""
    return f"({column} AT TIME ZONE 'UTC' AT TIME ZONE 'America/Barbados')::date"


def barbados_days(n: int) -> str:
    """A CTE body: the last `n` Barbados days, ending today, as column `d`."""
    return f"""
        SELECT generate_series(
            ({BARBADOS_TODAY} - INTERVAL '{n - 1} days')::date,
            {BARBADOS_TODAY},
            INTERVAL '1 day'
        )::date AS d"""
