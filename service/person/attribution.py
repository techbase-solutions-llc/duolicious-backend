"""Where a member came from, written at onboarding (health review finding 42).

The web sends two optional fields with POST /finish-onboarding
(ahavah-web src/lib/onboarding-attribution.ts):

  first_touch: object or null. Accepted keys, each a string of at most
    200 code points after trimming: utm_source, utm_medium, utm_campaign,
    utm_content, utm_term, referrer_host, code (an /i/ or /share/ invite
    code) and first_seen_at (ISO 8601).
  heard_about: string or null, at most 200 code points after trimming.

Anything else is dropped, never refused: an unknown key, a value that is
not a string, an empty or oversized value, a first_seen_at that is not a
date, and a value Postgres cannot store (a NUL, a lone surrogate). The
touch is visitor-controlled input, so the request that finishes
onboarding must not fail because of it.

lead_source is written on the source taxonomy (service/leads/sources.py):
utm:{source}/{campaign} when the touch has a utm_source, else
referral:{code} when an invite code came with it, else site:{host} for the
referring host. NULL when the touch has none of them. A source the
onboardee already carries (a couple tool's or the marriage checklist's,
set at /check-otp) is kept.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from service.leads.sources import referral_source, site_source, utm_label

VALUE_MAX_LENGTH = 200
HEARD_ABOUT_MAX_LENGTH = 200

FIRST_TOUCH_KEYS = (
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
    'referrer_host',
    'code',
    'first_seen_at',
)


def _clean_text(value: Any, max_length: int) -> Optional[str]:
    """Trimmed text of at most `max_length` code points, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_length or '\x00' in text:
        return None
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return None
    return text


def _is_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def clean_first_touch(value: Any) -> Optional[dict]:
    """The accepted first-touch values, or None when none are."""
    if not isinstance(value, dict):
        return None
    touch = {}
    for key in FIRST_TOUCH_KEYS:
        text = _clean_text(value.get(key), VALUE_MAX_LENGTH)
        if text is None:
            continue
        if key == 'first_seen_at' and not _is_timestamp(text):
            continue
        touch[key] = text
    return touch or None


def clean_heard_about(value: Any) -> Optional[str]:
    return _clean_text(value, HEARD_ABOUT_MAX_LENGTH)


def lead_source_from(touch: Optional[dict]) -> Optional[str]:
    if not touch:
        return None
    if touch.get('utm_source'):
        return utm_label(touch['utm_source'], touch.get('utm_campaign'))
    if touch.get('code'):
        return referral_source(touch['code'])
    if touch.get('referrer_host'):
        return site_source(touch['referrer_host'])
    return None


_Q_RECORD = """
    UPDATE person
       SET first_touch = %(first_touch)s::jsonb,
           heard_about = %(heard_about)s,
           lead_source = COALESCE(lead_source, %(lead_source)s)
     WHERE id = %(person_id)s
"""


def record_attribution(tx, person_id: int, first_touch: Any, heard_about: Any) -> None:
    """Writes the cleaned fields onto the new person, inside the
    finish-onboarding transaction. A failure here is rolled back to a
    savepoint and ignored, so it can never undo the sign-up."""
    touch = clean_first_touch(first_touch)
    answer = clean_heard_about(heard_about)
    source = lead_source_from(touch)
    if touch is None and answer is None:
        return
    tx.execute('SAVEPOINT record_attribution')
    try:
        tx.execute(_Q_RECORD, dict(
            person_id=person_id,
            first_touch=json.dumps(touch) if touch is not None else None,
            heard_about=answer,
            lead_source=source,
        ))
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT record_attribution')
    else:
        tx.execute('RELEASE SAVEPOINT record_attribution')
