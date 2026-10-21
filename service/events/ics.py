"""The calendar file a guest adds (TEC-1845), RFC 5545.

Times in UTC, text escaped, lines folded at 75 octets, CRLF line ends.
The location is only for a confirmed guest; the caller decides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_FOLD = 75


def _escape(text: str) -> str:
    return (text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n'))


def _utc(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _fold(line: str) -> list[str]:
    """Lines of at most 75 octets; a continuation starts with one space.
    Never splits a UTF-8 character."""
    out: list[str] = []
    current, size, limit = '', 0, _FOLD
    for ch in line:
        n = len(ch.encode('utf-8'))
        if size + n > limit:
            out.append(current)
            current, size, limit = ' ', 1, _FOLD
        current += ch
        size += n
    out.append(current)
    return out


def calendar_file(event: dict, *, location: Optional[str], url: str, now: datetime) -> str:
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Ahavah//Gatherings//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f"UID:{event['slug']}@ahavah.app",
        f'DTSTAMP:{_utc(now)}',
        f"DTSTART:{_utc(event['starts_at'])}",
        f"DTEND:{_utc(event['ends_at'])}",
        f"SUMMARY:{_escape(event['title'])}",
    ]
    if location:
        lines.append(f'LOCATION:{_escape(location)}')
    lines.append(f'URL:{url}')
    lines.append('STATUS:CANCELLED' if event.get('status') == 'cancelled' else 'STATUS:CONFIRMED')
    lines += ['END:VEVENT', 'END:VCALENDAR']
    return ''.join(f'{part}\r\n' for line in lines for part in _fold(line))
