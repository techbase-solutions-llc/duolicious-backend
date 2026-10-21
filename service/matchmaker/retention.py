"""What the matchmaker keeps, and for how long (TEC-1845, plan item 31).

  - A recommended single's address and the note are erased 7 days after
    the email settles (accepted, failed or skipped), and the outbox row's
    copy with them; recipient_key, a keyed hash, stays so the address hears
    from Ahavah once. Recommendation rows go 12 months after they were made.
  - An introduction's note stays while the pair is matched (it heads their
    chat) and is erased 30 days after an unmatched introduction closes.
  - A visitor's alert never confirmed goes a day after its link lapses; a
    stopped one went at once (alerts.stop).
  - Mentor sessions go a day after they lapse; an invitation never accepted
    is ended a day after it lapses; a mentor account serving nobody goes 30
    days after its last link ended.
  - Deleting an account deletes its matchmaker data (Q_DELETE_MATCHMAKER_
    DATA_OF): its mentor link (with its shares and outbox rows),
    recommendations sent to its address, its own pending ones (the sent
    ones lose its name and note), and a mentor account with its address.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

ERASE_AFTER = timedelta(days=7)
KEEP_FOR = timedelta(days=365)
NOTE_AFTER_CLOSE = timedelta(days=30)
GRACE = timedelta(days=1)
ACCOUNT_IDLE = timedelta(days=30)

_Q_TO_ERASE = """
    SELECT r.id AS rec_id, o.id AS outbox_id, o.email
      FROM recommendation r
      JOIN email_outbox o ON o.recommendation_id = r.id
     WHERE r.erased_at IS NULL
       AND o.state IN ('accepted', 'failed', 'skipped')
       AND COALESCE(o.sent_at, o.next_attempt_at, o.created_at) < %(cut)s
"""

_Q_CLOSED_NOTES = """
    UPDATE introduction SET note = NULL, note_erased_at = %(now)s
     WHERE note IS NOT NULL AND note_erased_at IS NULL
       AND status IN ('closed', 'rejected')
       AND COALESCE(CASE WHEN status = 'rejected' THEN reviewed_at END,
                    LEAST(closes_at, COALESCE(GREATEST(a_responded_at, b_responded_at), closes_at)))
           < %(cut)s
"""

_Q_IDLE_ACCOUNTS = """
    DELETE FROM mentor_account a
     WHERE NOT EXISTS (SELECT 1 FROM mentor_link l WHERE l.mentor_account_id = a.id AND l.revoked_at IS NULL)
       AND COALESCE((SELECT max(l.revoked_at) FROM mentor_link l WHERE l.mentor_account_id = a.id),
                    a.created_at) < %(cut)s
"""


def purge_matchmaker_data(tx, now: Optional[datetime] = None) -> dict:
    """The daily sweep (service/cron/leadretention). Returns the counts."""
    from emails.base import mask_email
    now = now or datetime.now(timezone.utc)
    rows = tx.execute(_Q_TO_ERASE, dict(cut=now - ERASE_AFTER)).fetchall()
    for r in rows:
        tx.execute("""UPDATE email_outbox SET email = %(m)s, payload = payload || '{"html": ""}'::jsonb
                       WHERE id = %(i)s""", dict(m=mask_email(r['email']), i=r['outbox_id']))
    erased = len({r['rec_id'] for r in rows})
    if rows:
        tx.execute("""UPDATE recommendation SET recipient_email = NULL, note = NULL, erased_at = %(now)s
                       WHERE id = ANY(%(i)s)""", dict(now=now, i=list({r['rec_id'] for r in rows})))
    deleted = tx.execute('DELETE FROM recommendation WHERE created_at < %(cut)s',
                         dict(cut=now - KEEP_FOR)).rowcount
    notes = tx.execute(_Q_CLOSED_NOTES, dict(now=now, cut=now - NOTE_AFTER_CLOSE)).rowcount
    unconfirmed = tx.execute(
        'DELETE FROM match_alert WHERE lead_id IS NOT NULL AND confirmed_at IS NULL AND confirm_by < %(cut)s',
        dict(cut=now - GRACE)).rowcount
    sessions = tx.execute('DELETE FROM mentor_session WHERE expires_at < %(cut)s',
                          dict(cut=now - GRACE)).rowcount
    invitations = tx.execute(
        """UPDATE mentor_link SET revoked_at = %(now)s, invite_token_hash = NULL
            WHERE confirmed_at IS NULL AND revoked_at IS NULL AND invite_expires_at < %(cut)s""",
        dict(now=now, cut=now - GRACE)).rowcount
    accounts = tx.execute(_Q_IDLE_ACCOUNTS, dict(cut=now - ACCOUNT_IDLE)).rowcount
    return dict(recommendations_erased=erased, recommendations_deleted=deleted, notes_erased=notes,
                unconfirmed_alerts=unconfirmed, mentor_sessions=sessions, mentor_accounts=accounts,
                invitations=invitations)


def matchmaker_keys(nes: Iterable[str]) -> list[str]:
    """The recipient keys of these normalised addresses: the binding `keys`
    of Q_DELETE_MATCHMAKER_DATA_OF (a keyed hash cannot be made in SQL)."""
    from service.matchmaker import address_key
    return [address_key(ne) for ne in nes if ne]


# One statement, as every deletion caller runs it beside Q_DELETE_TOOL_DATA_OF,
# BEFORE the person delete. Binds `nes` (each address through antiabuse
# normalize_email; an empty list when there is none), `ids` (the person ids)
# and `keys` (matchmaker_keys(nes)). Rows keyed on the person (alerts,
# introductions, shares, notes) go with it by ON DELETE CASCADE.
Q_DELETE_MATCHMAKER_DATA_OF = """
    WITH to_them AS (
        DELETE FROM recommendation WHERE recipient_key = ANY(%(keys)s::text[]) RETURNING id
    ), theirs_pending AS (
        DELETE FROM recommendation
         WHERE (sender_person_id = ANY(%(ids)s::int[]) OR sender_key = ANY(%(keys)s::text[]))
           AND status IN ('held', 'queued', 'rejected')
           AND NOT recipient_key = ANY(%(keys)s::text[])
        RETURNING id
    ), theirs_sent AS (
        UPDATE recommendation
           SET sender_person_id = NULL, sender_key = 'deleted:' || id, sender_first_name = NULL, note = NULL
         WHERE (sender_person_id = ANY(%(ids)s::int[]) OR sender_key = ANY(%(keys)s::text[]))
           AND status = 'sent'
           AND NOT recipient_key = ANY(%(keys)s::text[])
        RETURNING id
    ), accounts AS (
        SELECT id FROM mentor_account WHERE normalized_email = ANY(%(nes)s::text[])
    ), links AS (
        DELETE FROM mentor_link
         WHERE single_person_id = ANY(%(ids)s::int[])
            OR mentor_account_id IN (SELECT id FROM accounts)
            OR mentor_normalized_email = ANY(%(nes)s::text[])
        RETURNING id
    ), gone AS (
        DELETE FROM mentor_account WHERE id IN (SELECT id FROM accounts) RETURNING id
    )
    SELECT (SELECT count(*) FROM to_them) + (SELECT count(*) FROM theirs_pending)
         + (SELECT count(*) FROM theirs_sent) + (SELECT count(*) FROM links)
         + (SELECT count(*) FROM gone) AS n
"""


def link_recommendations_to_person(tx, person_id: int) -> None:
    """At finish-onboarding: a sent recommendation to the new member's
    address counts them as joined, and lead_source becomes 'intro' only
    when nothing else set it (first touch wins, plan item 26). Behind a
    savepoint: it never undoes the sign-up."""
    from service.leads.sources import INTRO
    from service.matchmaker import address_key
    tx.execute('SAVEPOINT mm_link_recommendations')
    try:
        row = tx.execute('SELECT normalized_email FROM person WHERE id = %(p)s', dict(p=person_id)).fetchone()
        if row and row['normalized_email']:
            n = tx.execute(
                """UPDATE recommendation SET joined_person_id = %(p)s
                    WHERE recipient_key = %(k)s AND status = 'sent' AND joined_person_id IS NULL""",
                dict(p=person_id, k=address_key(row['normalized_email']))).rowcount
            if n:
                tx.execute('UPDATE person SET lead_source = %(s)s WHERE id = %(p)s AND lead_source IS NULL',
                           dict(s=INTRO, p=person_id))
    except Exception:
        import traceback
        print(traceback.format_exc())
        tx.execute('ROLLBACK TO SAVEPOINT mm_link_recommendations')
    else:
        tx.execute('RELEASE SAVEPOINT mm_link_recommendations')
