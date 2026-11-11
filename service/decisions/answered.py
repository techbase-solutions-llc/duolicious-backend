"""A like the member has answered with a pass (11 Nov 2026).

Liked you posts a plain "nope", and a plain pass must not erase a like
(migration 0035), so the card came back on reload and stayed in the likes
count and the Matches badge. A pass the member made after the like arrived
answers that like; a pass made before it does not hide a later like.
Undoing the pass (Rewind, See passes again) brings the like back.

Liked you (Q_LIST_INCOMING_LIKES, whose count is the badge) and the emails
that count likes waiting all read this one fragment.
"""
from __future__ import annotations


def passed_after_like_sql(me: str, liker: str, liked_at: str) -> str:
    """SQL boolean: `me` passed on `liker` at or after `liked_at` (each an
    SQL expression). skipped.created_at moves to the time of the latest
    pass (antiabuse Q_INSERT_SKIPPED), so a pass made again after a later
    like counts."""
    return f"""EXISTS (
          SELECT 1 FROM skipped sk_ans
           WHERE sk_ans.subject_person_id = {me}
             AND sk_ans.object_person_id = {liker}
             AND sk_ans.created_at >= {liked_at}
      )"""
