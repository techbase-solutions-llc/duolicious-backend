"""Why members left (TEC-2158, migration 0100): the admin read of
exit_answer.

A row still tied to a person (person_id set, kept_at NULL) is inside the 7
days the deletion can be undone. It is left out of the counts and the list,
since an admin could match it to the member they see pending deletion; only
how many are waiting is returned. For the same reason the list gives the
month of an answer, never the day, and no id.
"""
from __future__ import annotations

from service.person.exit_answer import REASONS

_WAITING = '(person_id IS NOT NULL AND kept_at IS NULL)'

Q_COUNTS = f"""
    SELECT reason,
           COUNT(*) AS all_time,
           COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '90 days') AS last_90_days
      FROM exit_answer
     WHERE NOT {_WAITING}
     GROUP BY reason
"""

Q_WAITING = f"""
    SELECT COUNT(*) AS waiting
      FROM exit_answer
     WHERE {_WAITING}
"""

Q_LATEST = f"""
    SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') AS month,
           reason,
           note,
           gender,
           member_band,
           had_premium,
           CASE WHEN kept_at IS NOT NULL THEN 'kept' ELSE 'deleted' END AS state
      FROM exit_answer
     WHERE NOT {_WAITING}
     ORDER BY created_at DESC, id DESC
     LIMIT 50
"""


def exit_answers(tx) -> dict:
    counts = {r['reason']: r for r in tx.execute(Q_COUNTS).fetchall()}
    reasons = [
        dict(reason=reason,
             all_time=int(counts[reason]['all_time']) if reason in counts else 0,
             last_90_days=int(counts[reason]['last_90_days']) if reason in counts else 0)
        for reason in REASONS
    ]
    waiting = int(tx.execute(Q_WAITING).fetchone()['waiting'])
    answers = [dict(r) for r in tx.execute(Q_LATEST).fetchall()]
    return dict(waiting=waiting, counts=reasons, answers=answers)
