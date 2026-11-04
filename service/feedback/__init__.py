"""Public feedback capture. Caller owns the api_tx.

Append-only store written BEFORE the notification email fires, so a Resend
failure can never silently lose a submission (the row is the source of truth).
"""

from __future__ import annotations


_Q_INSERT = """
  INSERT INTO feedback (category, message, email, path, user_agent, person_id)
  VALUES (%(category)s, %(message)s, %(email)s, %(path)s, %(user_agent)s, %(person_id)s)
  RETURNING id
"""

_Q_COUNT_TODAY = """
  SELECT count(*) AS n FROM feedback
   WHERE created_at >= date_trunc('day', NOW())
"""


def insert(tx, *, category, message, email=None, path=None, user_agent=None,
           person_id=None) -> int:
    """`person_id` is the signed-in member who sent it, or None when the
    sender is anonymous (report rewards plan, 3 Nov 2026)."""
    row = tx.execute(_Q_INSERT, dict(
        category=category,
        message=message,
        email=email,
        path=path,
        user_agent=user_agent,
        person_id=person_id,
    )).fetchone()
    return int(row["id"])


def count_today(tx) -> int:
    """Rows inserted since midnight UTC — drives the global daily abuse cap."""
    return tx.execute(_Q_COUNT_TODAY).fetchone()["n"]
