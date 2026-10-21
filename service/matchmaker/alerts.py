"""Alerts: "Tell me when someone who fits joins" (TEC-1845).

A member's alert (1.1 to 1.10) is on as soon as it is saved: their address
is proved. A visitor's (3.1 to 3.9) is a lead with source alert:visitor and
waits for the link in its confirm email. Either names nobody: what is kept
is what they are looking for and when we last told them.

The stop token in "Stop these emails" is derived from the alert's id with
the unsubscribe secret, so every notice can carry the same link while only
its hash is stored. A member's link turns the alert's email off; a
visitor's deletes the alert.

Every function takes the caller's transaction.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from service.matchmaker import MatchmakerError
from service.matchmaker.criteria import clean_member_criteria, summary_line

CONFIRM_WINDOW = timedelta(days=7)
MAX_RESENDS = 3


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def stop_token(alert_id: int) -> str:
    """The alert's stop token: 32 URL-safe characters, the same every time."""
    from service.unsubscribe import _secret
    mac = hmac.new(_secret(), f'mm-stop|{alert_id}'.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode()[:32]


def _hash(token: str) -> str:
    from service.leads import token_hash
    return token_hash(token)


# ---------------------------------------------------------------------------
# A member's alert
# ---------------------------------------------------------------------------

def _member_row(tx, person_id: int) -> Optional[dict]:
    row = tx.execute('SELECT * FROM match_alert WHERE person_id = %(p)s', dict(p=person_id)).fetchone()
    return dict(row) if row else None


def _view(row: dict) -> dict:
    return dict(criteria=row['criteria'], notify_push=row['notify_push'],
                notify_email=row['notify_email'], state='on' if row['active'] else 'paused',
                summary=summary_line(row['criteria']))


def member_alert(tx, person_id: int) -> dict:
    """{alert, defaults}: the alert as the sheet shows it, or None, and the
    age band to fill a new one with (1.1: "filled from the member's current
    filters and saved age band"; the web adds the filters it holds)."""
    from service.search import AGE_CEILING, AGE_FLOOR, saved_age_band
    row = _member_row(tx, person_id)
    lo, hi = saved_age_band(tx, person_id)
    return dict(alert=_view(row) if row else None,
                defaults=dict(age_min=lo if lo is not None else AGE_FLOOR,
                              age_max=hi if hi is not None else AGE_CEILING))


def save_member_alert(tx, person_id: int, raw: dict, *, notify_push: bool,
                      notify_email: bool) -> dict:
    """Create or replace the member's alert, on at once. A saved change
    keeps its count window, so nobody is counted twice."""
    criteria = clean_member_criteria(raw)
    row = tx.execute(
        """INSERT INTO match_alert (person_id, criteria, notify_push, notify_email, active,
                                    confirmed_at)
           VALUES (%(p)s, %(c)s::jsonb, %(push)s, %(email)s, TRUE, NOW())
           ON CONFLICT (person_id) WHERE person_id IS NOT NULL DO UPDATE SET
               criteria = EXCLUDED.criteria, notify_push = EXCLUDED.notify_push,
               notify_email = EXCLUDED.notify_email, active = TRUE, paused_at = NULL,
               updated_at = NOW()
           RETURNING id, stop_token_hash""",
        dict(p=person_id, c=json.dumps(criteria), push=bool(notify_push),
             email=bool(notify_email))).fetchone()
    if row['stop_token_hash'] is None:
        tx.execute('UPDATE match_alert SET stop_token_hash = %(h)s WHERE id = %(i)s',
                   dict(h=_hash(stop_token(row['id'])), i=row['id']))
    return member_alert(tx, person_id)


def _set_active(tx, person_id: int, active: bool) -> dict:
    row = tx.execute(
        """UPDATE match_alert SET active = %(a)s,
                  paused_at = CASE WHEN %(a)s THEN NULL ELSE COALESCE(paused_at, NOW()) END,
                  updated_at = NOW()
            WHERE person_id = %(p)s RETURNING id""",
        dict(a=active, p=person_id)).fetchone()
    if row is None:
        raise MatchmakerError('no_alert', 404)
    return member_alert(tx, person_id)


def pause(tx, person_id: int) -> dict:
    """1.10: "Paused. What you are looking for is kept.\""""
    return _set_active(tx, person_id, False)


def resume(tx, person_id: int) -> dict:
    return _set_active(tx, person_id, True)


def delete_member_alert(tx, person_id: int) -> dict:
    tx.execute('DELETE FROM match_alert WHERE person_id = %(p)s', dict(p=person_id))
    return member_alert(tx, person_id)
