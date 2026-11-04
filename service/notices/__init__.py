"""In-app notices for one member (report rewards plan, 3 Nov 2026, TEC-2025).

A notice is shown until the member dismisses it. The first kind is the
thank-you for a report we fixed (service/feedback/rewards.py writes it). Every
read and write here is scoped to the signed-in member's own person_id: a
notice that is not theirs reads as not found.

Caller owns the api_tx.
"""
from __future__ import annotations

OPEN_LIMIT = 5

_Q_OPEN = """
    SELECT id, kind, title, body, tokens, premium_days, created_at, seen_at
      FROM member_notice
     WHERE person_id = %(person_id)s
       AND dismissed_at IS NULL
     ORDER BY created_at DESC, id DESC
     LIMIT %(limit)s
"""

_Q_DISMISS = """
    UPDATE member_notice
       SET seen_at = COALESCE(seen_at, NOW()),
           dismissed_at = COALESCE(dismissed_at, NOW())
     WHERE id = %(id)s
       AND person_id = %(person_id)s
    RETURNING id
"""

_Q_SEEN = """
    UPDATE member_notice
       SET seen_at = COALESCE(seen_at, NOW())
     WHERE id = %(id)s
       AND person_id = %(person_id)s
    RETURNING id
"""


def _iso(v):
    return v.isoformat() if v is not None else None


def list_open(tx, person_id: int, *, limit: int = OPEN_LIMIT) -> list[dict]:
    rows = tx.execute(_Q_OPEN, dict(person_id=person_id, limit=limit)).fetchall()
    return [dict(r, created_at=_iso(r['created_at']), seen_at=_iso(r['seen_at'])) for r in rows]


def dismiss(tx, person_id: int, notice_id: int) -> bool:
    """True when the member's own notice is now dismissed (dismissing twice
    is still True). False when no notice of theirs has that id."""
    return tx.execute(_Q_DISMISS, dict(id=notice_id, person_id=person_id)).fetchone() is not None


def mark_seen(tx, person_id: int, notice_id: int) -> bool:
    return tx.execute(_Q_SEEN, dict(id=notice_id, person_id=person_id)).fetchone() is not None
