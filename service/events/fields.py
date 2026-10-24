"""A gathering's fields made safe (TEC-1845): slugs, regions, feasts, tags,
the organiser's draft, text flags and the words for its time.

Nothing here touches the database. clean_draft raises EventError(reason,
400) with the field's reason, which the organiser's form maps to a line.
"""
from __future__ import annotations

import json
import re
import secrets
import unicodedata
import zoneinfo
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from service.events import EventError
from service.leads.sources import EVENT_SLUG_MAX, SLUG_RE

KINDS = ('assembly', 'fellowship_leader', 'ministry', 'other', 'ahavah')
MODES = ('in_person', 'online')
TAGS = ('singles_welcome', 'marriage_preparation')
REGIONS = ('africa', 'asia', 'europe', 'north-america', 'oceania', 'south-america', 'online')
VENUE_VISIBILITY = ('public', 'confirmed')

# The biblical English names, in the order of the year (export 4.10).
FEASTS: dict[str, str] = {
    'passover': 'Passover',
    'unleavened_bread': 'Unleavened Bread',
    'firstfruits': 'Firstfruits',
    'pentecost': 'Pentecost',
    'trumpets': 'Trumpets',
    'atonement': 'Day of Atonement',
    'tabernacles': 'Tabernacles',
    'last_great_day': 'Last Great Day',
}

TAG_LABELS = {'singles_welcome': 'Singles welcome', 'marriage_preparation': 'Marriage preparation'}

TITLE_MAX = 120
PLACE_MAX = 80
VENUE_MAX = 200
DESCRIPTION_MAX = 2000
ONLINE_URL_MAX = 500
CAPACITY_MAX = 5000
LONGEST = timedelta(days=7)

# The slug's words stop at 38 characters, leaving room for "-" and the
# 6 character suffix inside the source taxonomy's 45.
_SLUG_WORDS_MAX = EVENT_SLUG_MAX - 7
_SUFFIX_LEN = 6


def slug_for(title: str, suffix: Optional[str] = None) -> str:
    """The title's lower-case words joined by hyphens, cut on a word to at
    most 38 characters, then a 6 character suffix so two gatherings with
    one title never meet."""
    suffix = suffix or secrets.token_hex(3)
    plain = unicodedata.normalize('NFKD', title or '').encode('ascii', 'ignore').decode()
    words = re.findall(r'[a-z0-9]+', plain.lower())
    out = ''
    for w in words:
        nxt = f'{out}-{w}' if out else w
        if len(nxt) > _SLUG_WORDS_MAX:
            if not out:
                out = w[:_SLUG_WORDS_MAX]
            break
        out = nxt
    slug = f'{out or "gathering"}-{suffix}'
    assert SLUG_RE.match(slug) and len(slug) <= EVENT_SLUG_MAX
    return slug


@lru_cache(maxsize=1)
def _continents() -> dict[str, str]:
    path = Path(__file__).resolve().parent / 'continents.json'
    return json.loads(path.read_text(encoding='utf-8'))


def region_for(country: str) -> str:
    region = _continents().get(country) if isinstance(country, str) else None
    if region is None:
        raise ValueError('bad_country')
    return region


def countries() -> list[dict]:
    return [dict(name=n, region=r) for n, r in sorted(_continents().items())]


_NEWLINES = re.compile(r'\n{3,}')


def clean_text(value: object, max_len: int, *, multiline: bool = False) -> str:
    """Control characters out (a newline kept when multiline, 3 or more
    collapsed to 2), trimmed. Empty or over-length raises bad_text. Markup
    is kept as typed: every surface escapes it."""
    if not isinstance(value, str):
        raise EventError('bad_text', 400)
    text = value.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for ch in text:
        if ch == '\n' and multiline:
            out.append(ch)
        elif ch in '\t\n':
            out.append(' ')
        elif unicodedata.category(ch) in ('Cc', 'Cf', 'Cs', 'Co'):
            continue
        else:
            out.append(ch)
    text = ''.join(out)
    if multiline:
        text = '\n'.join(line.rstrip() for line in text.split('\n'))
        text = _NEWLINES.sub('\n\n', text)
    text = text.strip()
    if not text or len(text) > max_len:
        raise EventError('bad_text', 400)
    return text


def text_flag(*texts: Optional[str]) -> Optional[str]:
    """'rude' when any text is rude, 'scam' when any scores 0.5 or more on
    the romance-scam patterns, else None."""
    from antiabuse.antirude.profile import is_rude
    from antiabuse.romancescam import analyze_message
    present = [t for t in texts if isinstance(t, str) and t.strip()]
    if any(is_rude(t) for t in present):
        return 'rude'
    if any(analyze_message(t).total_score >= 0.5 for t in present):
        return 'scam'
    return None


def _text(value: object, max_len: int, reason: str, *, multiline: bool = False) -> str:
    try:
        return clean_text(value, max_len, multiline=multiline)
    except EventError:
        raise EventError(reason, 400)


def _optional_text(value: object, max_len: int, reason: str) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _text(value, max_len, reason)


def _when(value: object) -> datetime:
    if isinstance(value, datetime):
        when = value
    elif isinstance(value, str):
        try:
            when = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            raise EventError('bad_time', 400)
    else:
        raise EventError('bad_time', 400)
    if when.tzinfo is None or when.utcoffset() is None:
        raise EventError('bad_time', 400)
    return when


_TZ_LABEL = re.compile(r'^(?:[^\W\d_]|[ .\-])+$')


def _online_url(value: object) -> str:
    if not isinstance(value, str):
        raise EventError('bad_online_url', 400)
    url = value.strip()
    parts = urlsplit(url)
    if (not url.startswith('https://') or len(url) > ONLINE_URL_MAX or not parts.netloc
            or any(c.isspace() or unicodedata.category(c) == 'Cc' for c in url)):
        raise EventError('bad_online_url', 400)
    return url


def clean_draft(raw: dict, *, partial: bool = False) -> dict:
    """The organiser's fields made safe. With partial=True only the keys
    given are checked (an edit); the caller merges them over the stored
    gathering and checks the whole again for the rules across fields."""
    def has(key: str) -> bool:
        return not partial or key in raw

    out: dict = {}
    if has('title'):
        out['title'] = _text(raw.get('title'), TITLE_MAX, 'bad_title')
    if has('starts_at'):
        out['starts_at'] = _when(raw.get('starts_at'))
    if has('ends_at'):
        out['ends_at'] = _when(raw.get('ends_at'))
    if 'starts_at' in out and 'ends_at' in out:
        span = out['ends_at'] - out['starts_at']
        if span <= timedelta(0) or span > LONGEST:
            raise EventError('bad_time', 400)
    if has('tz'):
        tz = raw.get('tz')
        if not isinstance(tz, str) or tz not in zoneinfo.available_timezones():
            raise EventError('bad_tz', 400)
        out['tz'] = tz
    if has('tz_label'):
        label = raw.get('tz_label')
        label = label.strip() if isinstance(label, str) else ''
        if not 1 <= len(label) <= 40 or not _TZ_LABEL.match(label):
            raise EventError('bad_tz_label', 400)
        out['tz_label'] = label
    if has('mode'):
        if raw.get('mode') not in MODES:
            raise EventError('bad_mode', 400)
        out['mode'] = raw['mode']
    mode = out.get('mode')
    if mode == 'online':
        out['online_url'] = _online_url(raw.get('online_url'))
        out.update(city=None, country=None, venue=None, region='online')
    else:
        if has('city'):
            city = _optional_text(raw.get('city'), PLACE_MAX, 'bad_city')
            if city is None and mode == 'in_person':
                raise EventError('bad_city', 400)
            out['city'] = city
        if has('country'):
            country = raw.get('country')
            if country is None and mode is None:
                out['country'] = None
            else:
                try:
                    out['region'] = region_for(country)
                except ValueError:
                    raise EventError('bad_country', 400)
                out['country'] = country
        if has('venue'):
            out['venue'] = _optional_text(raw.get('venue'), VENUE_MAX, 'bad_venue')
        if mode == 'in_person':
            out['online_url'] = None
        elif has('online_url') and raw.get('online_url') is not None:
            out['online_url'] = _online_url(raw.get('online_url'))
    if has('venue_visibility'):
        vis = raw.get('venue_visibility', 'confirmed')
        if vis is None:
            vis = 'confirmed'
        if vis not in VENUE_VISIBILITY:
            raise EventError('bad_venue', 400)
        out['venue_visibility'] = vis
    if has('description'):
        desc = raw.get('description')
        if desc is None or (isinstance(desc, str) and not desc.strip()):
            out['description'] = ''
        else:
            out['description'] = _text(desc, DESCRIPTION_MAX, 'bad_description', multiline=True)
    if has('capacity'):
        cap = raw.get('capacity')
        if cap in (None, ''):
            out['capacity'] = None
        elif isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= CAPACITY_MAX:
            raise EventError('bad_capacity', 400)
        else:
            out['capacity'] = cap
    if has('tags'):
        tags = raw.get('tags') or []
        if not isinstance(tags, (list, tuple)) or any(t not in TAGS for t in tags):
            raise EventError('bad_tags', 400)
        out['tags'] = [t for t in TAGS if t in tags]
    if has('feast'):
        feast = raw.get('feast')
        if feast in (None, ''):
            out['feast'] = None
        elif feast not in FEASTS:
            raise EventError('bad_feast', 400)
        else:
            out['feast'] = feast
    if has('show_going'):
        out['show_going'] = raw.get('show_going') is True
    return out


_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
           'September', 'October', 'November', 'December')
_DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def _clock(t: datetime) -> str:
    if t.hour == 0 and t.minute == 0:
        return 'midnight'
    h = t.hour % 12 or 12
    ampm = 'am' if t.hour < 12 else 'pm'
    return f'{h}{ampm}' if t.minute == 0 else f'{h}.{t.minute:02d}{ampm}'


def _day(t: datetime, *, year: bool = True) -> str:
    words = f'{_DAYS[t.weekday()]} {t.day} {_MONTHS[t.month - 1]}'
    return f'{words} {t.year}' if year else words


def when_words(starts_at: datetime, ends_at: datetime, tz: str, tz_label: str) -> tuple[str, str]:
    """The gathering's day and time in its own zone, as the export writes
    them: ('Saturday 7 November 2026', '6pm to 9pm, Central Time'). One
    lasting a day or more names both days."""
    zone = zoneinfo.ZoneInfo(tz)
    s, e = starts_at.astimezone(zone), ends_at.astimezone(zone)
    if ends_at - starts_at < timedelta(days=1):
        return _day(s), f'{_clock(s)} to {_clock(e)}, {tz_label}'
    return _day(s), f'{_clock(s)}, {tz_label}, to {_day(e, year=e.year != s.year)}, {_clock(e)}'


def date_block(starts_at: datetime, tz: str) -> tuple[str, str, str]:
    """The start in the gathering's own zone as the email card's date
    block: ('Sat', '7', 'Nov'). An unknown zone raises
    zoneinfo.ZoneInfoNotFoundError, which the caller handles per card."""
    s = starts_at.astimezone(zoneinfo.ZoneInfo(tz))
    return _DAYS[s.weekday()][:3], str(s.day), _MONTHS[s.month - 1][:3]
