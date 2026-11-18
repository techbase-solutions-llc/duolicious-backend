"""The exit question (TEC-2158, migration 0100): why a member is leaving.

DELETE /account may carry {reason, note}. `record` writes the answer in the
soft delete's transaction; `mark_kept` closes it when the member keeps the
account (signing in again, or cancel-deletion).

Both are best-effort and must stay that way: the answer never blocks or
fails a deletion or a sign-in. Each runs inside a SAVEPOINT, so a failed
statement is rolled back alone and the caller's transaction carries on,
and every error is swallowed. The log line names the step and the error
class only: an error's own text can quote the row, and the note is the
member's words.

Nothing that names the member is stored: gender (Man or Woman), a band for
time as a member and whether they had Premium (the 'premium' entitlement,
or the older has_gold). person_id is held only while
the deletion can still be undone. Staff and testers store nothing.
"""
from __future__ import annotations

from typing import Any, Optional

REASONS = ('met_here', 'met_elsewhere', 'few_people', 'not_expected', 'break', 'other')
NOTE_MAX = 300
LOCK_TIMEOUT = '1s'

# An open row is one still tied to a person: closing it here keeps the
# partial unique index (one open row a person) from refusing the insert.
Q_CLOSE_OPEN = """
    UPDATE exit_answer
       SET kept_at = NOW(), person_id = NULL
     WHERE person_id = %(person_id)s
       AND kept_at IS NULL
"""

Q_INSERT = """
    INSERT INTO exit_answer (person_id, reason, note, gender, member_band, had_premium)
    SELECT p.id,
           %(reason)s,
           %(note)s,
           CASE WHEN g.name IN ('Man', 'Woman') THEN g.name END,
           CASE WHEN p.sign_up_time > LOCALTIMESTAMP - INTERVAL '1 month' THEN 'under_1_month'
                WHEN p.sign_up_time > LOCALTIMESTAMP - INTERVAL '6 months' THEN '1_to_6_months'
                ELSE 'over_6_months'
           END,
           ('premium' = ANY(COALESCE(p.entitlements, ARRAY[]::text[])) OR p.has_gold)
      FROM person p
      LEFT JOIN gender g ON g.id = p.gender_id
     WHERE p.id = %(person_id)s
       AND NOT (COALESCE(p.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod', 'tester']::text[])
"""

Q_MARK_KEPT = Q_CLOSE_OPEN


def clean_answer(body: Any) -> Optional[tuple[str, Optional[str]]]:
    """(reason, note) from a request body, or None when there is no usable
    answer: not an object, or a reason that is not one of ours. The note is
    trimmed, cut to NOTE_MAX characters and dropped when empty."""
    if not isinstance(body, dict):
        return None
    reason = body.get('reason')
    if not isinstance(reason, str) or reason not in REASONS:
        return None
    note = body.get('note')
    if isinstance(note, str):
        # Postgres text cannot hold a NUL.
        note = note.replace('\x00', '').strip()[:NOTE_MAX].rstrip() or None
    else:
        note = None
    return reason, note


def _best_effort(tx, step: str, statements: list[tuple[str, dict]]) -> bool:
    """Runs the statements inside a SAVEPOINT. On any error rolls back to
    it, logs the step and the error class, and returns False. Never raises."""
    name = f'exit_answer_{step}'
    try:
        tx.execute(f'SAVEPOINT {name}')
        try:
            # A lock wait on exit_answer must not hold up a deletion or a
            # sign-in: give up after a second. The caller's own setting is
            # put back after (a rollback to the savepoint restores it too).
            before = tx.execute(
                "SELECT current_setting('lock_timeout') AS v").fetchone()['v']
            tx.execute("SELECT set_config('lock_timeout', %(v)s, TRUE)",
                       dict(v=LOCK_TIMEOUT))
            for q, params in statements:
                tx.execute(q, params)
            tx.execute("SELECT set_config('lock_timeout', %(v)s, TRUE)", dict(v=before))
        except Exception as e:
            tx.execute(f'ROLLBACK TO SAVEPOINT {name}')
            print(f'exit_answer: {step} failed: {type(e).__name__}')
            return False
        tx.execute(f'RELEASE SAVEPOINT {name}')
        return True
    except Exception as e:
        print(f'exit_answer: {step} savepoint failed: {type(e).__name__}')
        return False


def record(tx, person_id: int, body: Any) -> bool:
    """Writes the member's answer, if the body holds one. Call it last in
    the soft delete's transaction."""
    try:
        answer = clean_answer(body)
    except Exception as e:
        print(f'exit_answer: record failed: {type(e).__name__}')
        return False
    if answer is None:
        return False
    reason, note = answer
    return _best_effort(tx, 'record', [
        (Q_CLOSE_OPEN, dict(person_id=person_id)),
        (Q_INSERT, dict(person_id=person_id, reason=reason, note=note)),
    ])


def mark_kept(tx, person_id: int) -> bool:
    """The member kept the account: close their open answer and cut it
    loose from them."""
    return _best_effort(tx, 'keep', [(Q_MARK_KEPT, dict(person_id=person_id))])
