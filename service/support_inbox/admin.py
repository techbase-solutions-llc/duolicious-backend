"""Admin > Support: the copied support messages and their handling
(TEC-2115). Caller owns the transaction.

A message is `open` until an admin marks it `handled` or `not_for_us`. Only
an open message can be marked: the row is locked first, so a double click or
two admins at once mark it once, and the second answers AlreadyHandled.
Replying stays in Gmail; each row carries a link that finds the message in
the owner's mailbox (None when the row has no message id). handled_by is
the email of the admin who marked it, or 'Imported'; handled_by_name is that
admin's first name when an account has the email, as resolved member
reports name their resolver.

`summary` is the counts and the inbox status only, for the admin's badge,
which polls it every minute on every screen: it reads no message.
"""
from __future__ import annotations

import re
from typing import Optional

from service.support_inbox import gmail_url, mailbox

SUPPORT_STATUSES = ('open', 'handled', 'not_for_us')
PAGE_SIZE = 50
PREVIEW_MAX = 200
STALE_AFTER_HOURS = 24


class MessageNotFound(Exception):
    pass


class AlreadyHandled(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


# Open messages come oldest first, so the longest waits are never on a later
# page; handled, not for us and all come newest first.
_Q_LIST = """
    SELECT m.id, m.gmail_thread_id, m.rfc_message_id, m.from_address, m.from_name, m.subject,
           m.body_text, m.received_at, m.status, m.handled_by, m.handled_at,
           floor(extract(epoch FROM NOW() - m.received_at) / 3600)::int AS age_hours,
           p.uuid::text AS member_uuid, p.name AS member_name
      FROM support_message m
      LEFT JOIN person p ON p.id = m.person_id
     WHERE %(status)s::text IS NULL OR m.status = %(status)s::text
     ORDER BY {order}
     LIMIT %(limit)s OFFSET %(offset)s
"""
Q_LIST_OLDEST = _Q_LIST.format(order='m.received_at ASC, m.id ASC')
Q_LIST_NEWEST = _Q_LIST.format(order='m.received_at DESC, m.id DESC')

_Q_COUNTS = "SELECT status, count(*)::int AS n FROM support_message GROUP BY status"

_Q_STATE = """
    SELECT last_checked_at, last_ok_at, last_error, backfill_done
      FROM support_inbox_state WHERE mailbox = %(m)s
"""


def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


def _preview(body: str) -> str:
    text = re.sub(r'\s+', ' ', body or '').strip()
    return text if len(text) <= PREVIEW_MAX else text[:PREVIEW_MAX - 1].rstrip() + '…'


# The first name of the account with each normalised email, as resolved
# member reports name their resolver (split_part of person.name). The
# oldest account when two share one.
_Q_HANDLER_NAMES = """
    SELECT DISTINCT ON (normalized_email)
           normalized_email, NULLIF(split_part(name, ' ', 1), '') AS first_name
      FROM person
     WHERE normalized_email = ANY(%(emails)s)
     ORDER BY normalized_email, id
"""


def _handler_names(tx, handled_by: set) -> dict:
    """handled_by value -> the admin's first name, for those an account
    has; 'Imported' and unknown emails are left out."""
    from antiabuse.antispam.signupemail import normalize_email
    normalised = {h: normalize_email(h.strip()) for h in handled_by if h and '@' in h}
    if not normalised:
        return {}
    rows = tx.execute(_Q_HANDLER_NAMES, dict(emails=sorted(set(normalised.values())))).fetchall()
    names = {r['normalized_email']: r['first_name'] for r in rows}
    return {h: names.get(ne) for h, ne in normalised.items() if names.get(ne)}


def _counts(tx) -> dict:
    counts = {s: 0 for s in SUPPORT_STATUSES}
    for r in tx.execute(_Q_COUNTS).fetchall():
        counts[r['status']] = r['n']
    return counts


def _inbox(tx, enabled: bool) -> dict:
    box = mailbox()
    state = tx.execute(_Q_STATE, dict(m=box)).fetchone()
    return dict(
        enabled=enabled,
        mailbox=box,
        last_checked_at=_iso(state['last_checked_at']) if state else None,
        last_ok_at=_iso(state['last_ok_at']) if state else None,
        last_error=state['last_error'] if state else None,
        backfill_done=bool(state['backfill_done']) if state else False,
    )


def summary(tx, *, enabled: bool = False) -> dict:
    """The counts by status and the inbox status; no message."""
    return dict(counts=_counts(tx), inbox=_inbox(tx, enabled))


def list_messages(tx, *, status: Optional[str], page: int = 1, enabled: bool = False) -> dict:
    query = Q_LIST_OLDEST if status == 'open' else Q_LIST_NEWEST
    rows = tx.execute(query, dict(status=status, limit=PAGE_SIZE + 1,
                                  offset=(page - 1) * PAGE_SIZE)).fetchall()
    names = _handler_names(tx, {r['handled_by'] for r in rows[:PAGE_SIZE] if r['handled_by']})
    return dict(
        messages=[dict(
            id=int(r['id']),
            from_address=r['from_address'],
            from_name=r['from_name'],
            subject=r['subject'],
            preview=_preview(r['body_text']),
            body_text=r['body_text'],
            received_at=r['received_at'].isoformat(),
            age_hours=r['age_hours'],
            status=r['status'],
            handled_by=r['handled_by'],
            handled_by_name=names.get(r['handled_by']),
            handled_at=_iso(r['handled_at']),
            member=(dict(uuid=r['member_uuid'], name=r['member_name'])
                    if r['member_uuid'] else None),
            gmail_url=gmail_url(rfc_message_id=r['rfc_message_id'], thread_id=r['gmail_thread_id']),
        ) for r in rows[:PAGE_SIZE]],
        counts=_counts(tx),
        page=page,
        page_size=PAGE_SIZE,
        has_more=len(rows) > PAGE_SIZE,
        inbox=_inbox(tx, enabled),
    )


_Q_LOCK = """
    SELECT m.id, m.status, p.uuid::text AS member_uuid
      FROM support_message m
      LEFT JOIN person p ON p.id = m.person_id
     WHERE m.id = %(id)s
       FOR UPDATE OF m
"""

_Q_CLOSE = """
    UPDATE support_message
       SET status = %(status)s, handled_at = NOW(), handled_by = %(by)s
     WHERE id = %(id)s AND status = 'open'
    RETURNING handled_at
"""


def mark(tx, message_id: int, status: str, *, handled_by: str) -> dict:
    """Close an open message as `handled` or `not_for_us`. Run inside one
    READ COMMITTED transaction, so the row lock waits for a concurrent
    handler and then sees its result."""
    if status not in ('handled', 'not_for_us'):
        raise ValueError(status)
    row = tx.execute(_Q_LOCK, dict(id=message_id)).fetchone()
    if row is None:
        raise MessageNotFound(message_id)
    if row['status'] != 'open':
        raise AlreadyHandled(row['status'])
    closed = tx.execute(_Q_CLOSE, dict(id=message_id, status=status, by=handled_by)).fetchone()
    if closed is None:  # the lock above makes this unreachable
        raise AlreadyHandled('unknown')
    return dict(id=message_id, status=status, handled_at=closed['handled_at'].isoformat(),
                member_uuid=row['member_uuid'])


class AlreadyOpen(Exception):
    pass


_Q_REOPEN = """
    UPDATE support_message
       SET status = 'open', handled_at = NULL, handled_by = NULL
     WHERE id = %(id)s AND status <> 'open'
    RETURNING id
"""


def reopen(tx, message_id: int) -> dict:
    """Put a handled or not-for-us message back to open, for a mark made by
    mistake. Same lock as `mark`, so two reopens at once reopen it once."""
    row = tx.execute(_Q_LOCK, dict(id=message_id)).fetchone()
    if row is None:
        raise MessageNotFound(message_id)
    if row['status'] == 'open':
        raise AlreadyOpen()
    if tx.execute(_Q_REOPEN, dict(id=message_id)).fetchone() is None:  # unreachable under the lock
        raise AlreadyOpen()
    return dict(id=message_id, status='open', previous=row['status'], member_uuid=row['member_uuid'])


# Message number and age only: no subject, no text and no address, so the
# owner's alert email carries nothing a member wrote. The age counts from
# when the message arrived or when it was copied in, whichever is later: a
# message imported open by the first full read is not overdue the moment it
# lands, and a new one is copied within minutes of arriving.
_Q_STALE_OPEN = """
    SELECT id,
           floor(extract(epoch FROM NOW() - GREATEST(received_at, created_at)) / 3600)::int AS age_hours
      FROM support_message
     WHERE status = 'open'
       AND GREATEST(received_at, created_at) < NOW() - make_interval(hours => %(hours)s)
     ORDER BY GREATEST(received_at, created_at), id
"""


def stale_open(tx, *, hours: int = STALE_AFTER_HOURS) -> list[dict]:
    return [dict(r) for r in tx.execute(_Q_STALE_OPEN, dict(hours=hours)).fetchall()]
