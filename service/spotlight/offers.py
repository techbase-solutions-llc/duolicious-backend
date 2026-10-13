"""What became of a member's card offers (health review, 13 Oct 2026,
finding 78).

Why offers stopped after 22 Sep: a member-of-the-week card is only ever
created by an admin pressing the button, and welcomes go only to members
who opted in within 14 days of joining. Person 27, the one opted-in member
who is not staff, was offered two cards (20 and 22 Sep); both sat
unanswered and the daily expiry cancelled them on 28 and 30 Sep. The
expiry told nobody: the tick logged a count and the cron path wrote no
audit row, the suggestion list kept offering the member as though nothing
had happened, and nothing said a card had lapsed. So nobody knew to try
again, and nobody did.

This module is the record that was missing. `expire_lapsed` names each
card that lapses (once per card, not once per platform row) so the route
can report and audit it; `last_offers` says what happened to each member's
most recent card, so the suggestion list can show it and leave out a member
whose card is still waiting. Whether to offer again stays a person's call:
nothing here offers a card.

Every function runs inside the caller's api_tx; none opens one.
"""
from __future__ import annotations

from typing import Optional

# The kinds a member is asked to approve. A roundup or brand post has no
# subject and no offer.
OFFER_KINDS = ('welcome', 'member_of_week')

# A card the member can still act on, or that is on its way out.
OPEN_STATUSES = ('awaiting_member', 'awaiting_render', 'review', 'scheduled', 'processing')

_Q_EXPIRE = """
    UPDATE publishing_queue SET status = 'cancelled', error = 'approval_expired', updated_at = NOW()
     WHERE status = 'awaiting_member' AND created_at < NOW() - make_interval(days => %(d)s)
    RETURNING request_key, subject_person_id, kind
"""

_Q_LAST = """
    SELECT DISTINCT ON (subject_person_id)
           subject_person_id, kind, request_key, status, error, updated_at
      FROM publishing_queue
     WHERE subject_person_id = ANY(%(ids)s) AND kind IN ('welcome', 'member_of_week')
     ORDER BY subject_person_id, created_at DESC, updated_at DESC
"""

# Distinct cards, not platform rows: one card is two rows.
_Q_LAPSED_COUNT = """
    SELECT count(DISTINCT request_key) AS n FROM publishing_queue
     WHERE kind IN ('welcome', 'member_of_week')
       AND status = 'cancelled' AND error = 'approval_expired'
       AND updated_at > NOW() - make_interval(days => %(d)s)
"""


def expire_lapsed(tx, days: int = 7) -> tuple[list[dict], int]:
    """Cancel every card left awaiting the member longer than `days`, as
    `queue.expire_member_approvals` did. Returns one entry per card
    (request_key, person_id, kind) and the number of rows cancelled, which
    is what the route has always reported as `cancelled`."""
    rows = tx.execute(_Q_EXPIRE, dict(d=days)).fetchall()
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(r['request_key'], dict(
            request_key=r['request_key'], person_id=r['subject_person_id'], kind=r['kind']))
    out = list(seen.values())
    out.sort(key=lambda x: x['request_key'])
    return out, len(rows)


def _outcome(status: str, error: Optional[str]) -> str:
    if status in OPEN_STATUSES:
        return 'open'
    if status == 'published':
        return 'published'
    if error == 'approval_expired':
        return 'lapsed'
    if error == 'member_skipped':
        return 'skipped'
    return 'cancelled'


def last_offers(tx, person_ids: list[int]) -> dict[int, dict]:
    """Each member's most recent card offer: kind, outcome (open, published,
    lapsed, skipped or cancelled) and when it last changed. A member never
    offered a card is absent."""
    if not person_ids:
        return {}
    out = {}
    for r in tx.execute(_Q_LAST, dict(ids=list(person_ids))).fetchall():
        out[r['subject_person_id']] = dict(
            kind=r['kind'], outcome=_outcome(r['status'], r['error']),
            at=r['updated_at'].isoformat() if r['updated_at'] else None)
    return out


def suggestable(last_offer: Optional[dict]) -> bool:
    """A member whose card is still open cannot be offered another (the
    `already_offered` guard in queue.create_candidate refuses it), so the
    suggestion list leaves them out rather than offer a button that fails."""
    return not last_offer or last_offer.get('outcome') != 'open'


def lapsed_count(tx, days: int = 30) -> int:
    """Cards that lapsed unanswered in the last `days`, one per card."""
    return int(tx.execute(_Q_LAPSED_COUNT, dict(d=days)).fetchone()['n'])
