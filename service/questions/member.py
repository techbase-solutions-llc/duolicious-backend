"""What one member sees of the quick questions (TEC-1845).

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from service.questions.bank import LIVE, question_json, question_state
from service.questions.schedule import current_drop

_Q_CATCH_UP = f"""
    SELECT b.key, b.text, b.format, b.options
      FROM prompt_bank b
     WHERE {LIVE}
       AND b.key <> ALL(%(skip)s)
       AND NOT EXISTS (SELECT 1 FROM prompt_answer a
                        WHERE a.person_id = %(p)s AND a.prompt_key = b.key)
     ORDER BY b.sort, b.key
"""

_Q_DECLINED = """
    SELECT question_catchup_declined_at IS NOT NULL AS declined FROM person WHERE id = %(p)s
"""

# The first "Not now" is the one kept.
_Q_DECLINE = """
    UPDATE person SET question_catchup_declined_at = COALESCE(question_catchup_declined_at, NOW())
     WHERE id = %(p)s
"""


def current_for(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    drop = current_drop(tx, now)
    if drop is None:
        return dict(current=None)
    return dict(current=dict(live_on=drop['live_on'].isoformat(),
                             **question_state(tx, person_id, drop['question'])))


def catch_up_for(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    """Every live question the member has not answered, leaving out this
    week's, which has the card to itself (owner decision 10)."""
    drop = current_drop(tx, now)
    skip = [drop['question']['key']] if drop else []
    row = tx.execute(_Q_DECLINED, dict(p=person_id)).fetchone()
    return dict(declined=bool(row and row['declined']),
                questions=[question_json(r) for r in
                           tx.execute(_Q_CATCH_UP, dict(p=person_id, skip=skip)).fetchall()])


def decline_catch_up(tx, person_id: int) -> None:
    tx.execute(_Q_DECLINE, dict(p=person_id))
