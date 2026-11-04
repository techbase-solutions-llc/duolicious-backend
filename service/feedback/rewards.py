"""Handling a report, and thanking the member (report rewards plan, 3 Nov 2026,
TEC-2025).

The admin marks a report `fixed` or `not_a_fault`. Only a report still `new`
can be handled: the row is locked first, so a double click, or two admins at
once, cannot pay twice (the second answers AlreadyHandled).

`fixed` pays the referral reward, the same way referrals pay it (a
token_ledger row, reason `report_reward`, and extend_premium_tx), and writes
one in-app notice, all in the caller's single transaction:

  - the member is the report's person_id; failing that, the one person whose
    account email matches the report's email, ignoring case. No member: the
    report is closed with no reward and no notice.
  - a member with REPORT_REWARD_CAP rewarded reports in the last
    REPORT_REWARD_WINDOW_DAYS days gets the notice without a reward.
  - the admin can choose no reward; the notice is still written.

`not_a_fault` closes the report with no reward and no notice.

Nothing here sends email or push. The member sees the notice in the app.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

REPORT_REWARD_TOKENS = 5
REPORT_REWARD_PREMIUM_DAYS = 30
REPORT_REWARD_CAP = 3
REPORT_REWARD_WINDOW_DAYS = 30

NOTICE_LINE_MAX = 200
NOTICE_TITLE = 'Thanks for your report'
NOTICE_KIND = 'report_thanks'


class FeedbackNotFound(Exception):
    pass


class AlreadyHandled(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class BadNoticeLine(ValueError):
    pass


def clean_notice_line(raw: Optional[str]) -> str:
    """The admin's one line to the member: trimmed, inner whitespace (and any
    line break) collapsed to one space, 1 to NOTICE_LINE_MAX characters. A
    line with no closing punctuation gets a full stop, so the reward sentence
    after it reads as a second sentence."""
    line = re.sub(r'\s+', ' ', raw or '').strip()
    if not line:
        raise BadNoticeLine('notice_line is required')
    if len(line) > NOTICE_LINE_MAX:
        raise BadNoticeLine(f'notice_line is longer than {NOTICE_LINE_MAX} characters')
    # House copy has no exclamation marks: a closing one becomes a full stop.
    line = line.rstrip('!').rstrip()
    if not line:
        raise BadNoticeLine('notice_line is required')
    if line[-1] not in '.?':
        line += '.'
    return line


def reward_sentence(tokens: int, days: int) -> str:
    return f'You have {tokens} more tokens and {days} more days of Premium.'


def notice_body(line: str, *, tokens: int, days: int) -> str:
    if tokens > 0 or days > 0:
        return f'{line} {reward_sentence(tokens, days)}'
    return line


_Q_LOCK_FEEDBACK = """
    SELECT id, status, person_id, email
      FROM feedback
     WHERE id = %(id)s
       FOR UPDATE
"""

_Q_PERSON_BY_ID = """
    SELECT id, uuid::text AS uuid FROM person WHERE id = %(id)s
"""

# Exactly one account with that address, ignoring case. Two would be a data
# fault; neither gets the reward rather than guessing.
_Q_PERSON_BY_EMAIL = """
    SELECT id, uuid::text AS uuid
      FROM person
     WHERE lower(email) = lower(%(email)s)
     LIMIT 2
"""

# Locks the member's row, so two of their reports handled at once count the
# cap one after the other.
_Q_LOCK_PERSON = """
    SELECT id FROM person WHERE id = %(id)s FOR UPDATE
"""

_Q_REWARDED_IN_WINDOW = """
    SELECT count(*) AS n
      FROM feedback
     WHERE person_id = %(person_id)s
       AND status = 'fixed'
       AND (reward_tokens > 0 OR reward_days > 0)
       AND handled_at > NOW() - make_interval(days => %(days)s)
"""

_Q_CLOSE = """
    UPDATE feedback
       SET status = %(status)s,
           handled_at = NOW(),
           handled_by = %(by)s,
           person_id = COALESCE(person_id, %(person_id)s),
           reward_tokens = %(tokens)s,
           reward_days = %(days)s,
           notice_line = %(line)s
     WHERE id = %(id)s
       AND status = 'new'
    RETURNING handled_at
"""

_Q_INSERT_NOTICE = """
    INSERT INTO member_notice (person_id, kind, title, body, tokens, premium_days, feedback_id)
    VALUES (%(person_id)s, %(kind)s, %(title)s, %(body)s, %(tokens)s, %(days)s, %(feedback_id)s)
    RETURNING id
"""


@dataclass
class Member:
    id: int
    uuid: str
    via: str  # 'session' or 'email'


def _lock_new(tx, feedback_id: int) -> dict:
    row = tx.execute(_Q_LOCK_FEEDBACK, dict(id=feedback_id)).fetchone()
    if row is None:
        raise FeedbackNotFound(feedback_id)
    if row['status'] != 'new':
        raise AlreadyHandled(row['status'])
    return row


def resolve_member(tx, *, person_id: Optional[int], email: Optional[str]) -> Optional[Member]:
    if person_id is not None:
        row = tx.execute(_Q_PERSON_BY_ID, dict(id=person_id)).fetchone()
        if row is not None:
            return Member(id=int(row['id']), uuid=row['uuid'], via='session')
    address = (email or '').strip()
    if not address:
        return None
    rows = tx.execute(_Q_PERSON_BY_EMAIL, dict(email=address)).fetchall()
    if len(rows) != 1:
        return None
    return Member(id=int(rows[0]['id']), uuid=rows[0]['uuid'], via='email')


def rewarded_in_window(tx, person_id: int) -> int:
    return int(tx.execute(
        _Q_REWARDED_IN_WINDOW, dict(person_id=person_id, days=REPORT_REWARD_WINDOW_DAYS),
    ).fetchone()['n'])


def mark_fixed(tx, feedback_id: int, *, notice_line: Optional[str], reward: bool,
               handled_by: str) -> dict:
    """Close a `new` report as fixed, pay the reward and write the notice.
    Run inside one READ COMMITTED transaction, so the row lock waits for a
    concurrent handler and then sees its result.

    Returns:
      outcome       'paid' | 'capped' | 'no_reward' | 'member_none'
      member        'session' | 'email' | 'none'
      reward_tokens, reward_days   what was paid (0 when nothing was)
      notice_id     the notice written, or None
    """
    line = clean_notice_line(notice_line)
    fb = _lock_new(tx, feedback_id)
    member = resolve_member(tx, person_id=fb['person_id'], email=fb['email'])

    tokens = days = 0
    notice_id = None
    if member is None:
        outcome = 'member_none'
    else:
        tx.execute(_Q_LOCK_PERSON, dict(id=member.id))
        if not reward:
            outcome = 'no_reward'
        elif rewarded_in_window(tx, member.id) >= REPORT_REWARD_CAP:
            outcome = 'capped'
        else:
            outcome = 'paid'
            tokens, days = REPORT_REWARD_TOKENS, REPORT_REWARD_PREMIUM_DAYS
            from service.tokens import credit
            credit(tx, member.uuid, tokens, reason='report_reward',
                   metadata={'feedback_id': str(feedback_id)})
            from service.entitlements import extend_premium_tx
            extend_premium_tx(tx, member.uuid, days)

    closed = tx.execute(_Q_CLOSE, dict(
        id=feedback_id, status='fixed', by=handled_by,
        person_id=member.id if member else None,
        tokens=tokens, days=days, line=line,
    )).fetchone()
    if closed is None:  # the lock above makes this unreachable; never pay twice
        raise AlreadyHandled('unknown')

    if member is not None:
        notice_id = int(tx.execute(_Q_INSERT_NOTICE, dict(
            person_id=member.id, kind=NOTICE_KIND, title=NOTICE_TITLE,
            body=notice_body(line, tokens=tokens, days=days),
            tokens=tokens, days=days, feedback_id=feedback_id,
        )).fetchone()['id'])

    return dict(
        id=feedback_id,
        status='fixed',
        outcome=outcome,
        member=member.via if member else 'none',
        paid=outcome == 'paid',
        capped=outcome == 'capped',
        reward_tokens=tokens,
        reward_days=days,
        notice_id=notice_id,
        handled_at=closed['handled_at'].isoformat(),
    )


def mark_not_a_fault(tx, feedback_id: int, *, handled_by: str) -> dict:
    """Close a `new` report with no reward and no notice."""
    _lock_new(tx, feedback_id)
    closed = tx.execute(_Q_CLOSE, dict(
        id=feedback_id, status='not_a_fault', by=handled_by,
        person_id=None, tokens=0, days=0, line=None,
    )).fetchone()
    if closed is None:
        raise AlreadyHandled('unknown')
    return dict(id=feedback_id, status='not_a_fault', outcome='closed',
                handled_at=closed['handled_at'].isoformat())


# ---------------------------------------------------------------------------
# the admin's list
# ---------------------------------------------------------------------------

FEEDBACK_STATUSES = ('new', 'fixed', 'not_a_fault')

# The same report fields the System tab's health read already returns
# (Q_FEEDBACK_RECENT: id, category, message, email, path, created_at), plus
# the handling. has_member is the rule mark_fixed resolves the member by.
Q_FEEDBACK_LIST = """
    SELECT f.id, f.category, f.message, f.email, f.path, f.created_at,
           f.status, f.handled_at, f.reward_tokens, f.reward_days, f.notice_line,
           floor(extract(epoch FROM NOW() - f.created_at) / 3600)::int AS age_hours,
           (f.person_id IS NOT NULL
            OR (f.email IS NOT NULL
                AND (SELECT count(*) FROM person p
                      WHERE lower(p.email) = lower(f.email)) = 1)) AS has_member
      FROM feedback f
     WHERE %(status)s::text IS NULL OR f.status = %(status)s::text
     ORDER BY f.created_at DESC, f.id DESC
     LIMIT %(limit)s
"""

Q_FEEDBACK_COUNTS = """
    SELECT status, count(*)::int AS n FROM feedback GROUP BY status
"""


def list_feedback(tx, *, status: Optional[str], limit: int = 50) -> dict:
    rows = tx.execute(Q_FEEDBACK_LIST, dict(status=status, limit=limit)).fetchall()
    counts = {s: 0 for s in FEEDBACK_STATUSES}
    for r in tx.execute(Q_FEEDBACK_COUNTS).fetchall():
        counts[r['status']] = r['n']
    return dict(
        feedback=[dict(
            r,
            created_at=r['created_at'].isoformat(),
            handled_at=r['handled_at'].isoformat() if r['handled_at'] else None,
        ) for r in rows],
        counts=counts,
    )


# ---------------------------------------------------------------------------
# reports nobody has answered (the send guard's daily owner alert)
# ---------------------------------------------------------------------------

STALE_AFTER_HOURS = 24

# Report number, category and age only: no message text and no address, so
# the alert email carries nothing a member wrote.
Q_STALE_NEW = """
    SELECT id, category,
           floor(extract(epoch FROM NOW() - created_at) / 3600)::int AS age_hours
      FROM feedback
     WHERE status = 'new'
       AND created_at < NOW() - make_interval(hours => %(hours)s)
     ORDER BY created_at, id
"""


def stale_new(tx, *, hours: int = STALE_AFTER_HOURS) -> list[dict]:
    return [dict(r) for r in tx.execute(Q_STALE_NEW, dict(hours=hours)).fetchall()]
