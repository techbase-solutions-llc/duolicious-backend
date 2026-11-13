"""A like the member has answered with a pass.

Liked you posts a plain "nope", and a plain pass must not erase a like
(migration 0035), so the card came back on reload and stayed in the likes
count and the Matches badge. Since 11 Nov 2026 a pass hides the like.

Since 13 Nov 2026 (TEC-2085, decision 10) a pass removes that person from
Liked you for good, as a pass does in the deck: whenever the pass was made,
before or after the like, and whatever they do afterwards (a like taken back
and given again included). Undoing the pass (Rewind, See passes again, the
Undo on Liked you) deletes the skip and brings the like back.

Liked you (Q_LIST_INCOMING_LIKES, whose count is the badge) and the emails
that count likes waiting all read this one fragment.
"""
from __future__ import annotations


def passed_on_liker_sql(me: str, liker: str) -> str:
    """SQL boolean: `me` has a pass standing on `liker` (each an SQL
    expression). Reports are is_blocked_pair's, which every caller reads
    as well."""
    return f"""EXISTS (
          SELECT 1 FROM skipped sk_ans
           WHERE sk_ans.subject_person_id = {me}
             AND sk_ans.object_person_id = {liker}
      )"""
