"""ISO 8601 for every admin endpoint added in TEC-1897.

Flask writes a raw datetime as an RFC 2822 date, and a naive TIMESTAMP
column here holds UTC (person.last_online_time, skipped.created_at,
visited.updated_at), which the admin would read as local time. So a naive
datetime leaves marked as UTC, an aware one as it is, and a date as
YYYY-MM-DD.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping


def iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def iso_row(row: Mapping) -> dict:
    return {k: iso(v) for k, v in dict(row).items()}
