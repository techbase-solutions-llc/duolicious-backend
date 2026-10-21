"""Recommend Ahavah to a single (TEC-1845, 5a).

Anyone signed in can do it: a member, or a visitor who confirmed their own
address with the 6-digit code first (owner decision 5). The single gets one
email with the note, and the member's invite link when a member sent it.
Nothing about the single is shared, and an address hears from Ahavah once
ever, whoever sends (recipient_key, kept 12 months after the address is
erased, service/matchmaker/retention.py).

Every refusal a sender could learn from answers exactly as a send: the
address belongs to a member, it was recommended before, it is the sender's
own. A refusal still counts against the sender's week, as a send would, so
the allowance says nothing either: it is kept as a 'rejected' row with no
address and a key that matches nobody (flag_reason 'refused'). A flagged
note waits for Moderation > Text and the sender sees the same answer.

Limits: 5 a week per sender, the week from Monday 00:00 UTC.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg

from service.matchmaker import MatchmakerError, address_key

WEEKLY_LIMIT = 5
DEFAULT_NOTE = 'I think you would be a good fit for Ahavah.'
NOTE_MAX = 500

_EMAIL_RE = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')


def note_flag(note: Optional[str]) -> Optional[str]:
    """Why a note waits for review: 'rude', 'scam' (0.5 or more on the
    romance-scam patterns), 'contact' (a URL, an email address or 7 or more
    digits), else None. Shared with introductions."""
    from antiabuse.antirude.profile import is_rude
    from antiabuse.antispam.urldetector import has_url
    from antiabuse.romancescam import analyze_message
    if not isinstance(note, str) or not note.strip():
        return None
    if is_rude(note):
        return 'rude'
    if analyze_message(note).total_score >= 0.5:
        return 'scam'
    if has_url(note) or _EMAIL_RE.search(note) or sum(ch.isdigit() for ch in note) >= 7:
        return 'contact'
    return None


def clean_note(value: object, max_len: int = NOTE_MAX, *, default: Optional[str] = None) -> str:
    """A note as typed, control characters out, newlines kept (at most one
    blank line), trimmed. Empty is `default`, or bad_note without one."""
    from service.events import EventError
    from service.events.fields import clean_text
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is not None:
            return default
        raise MatchmakerError('bad_note', 400)
    try:
        return clean_text(value, max_len, multiline=True)
    except EventError:
        raise MatchmakerError('bad_note', 400)


def week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of now's week."""
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def next_week_day() -> str:
    return 'Monday'


def _used(tx, sender_key: str, now: datetime) -> int:
    return int(tx.execute(
        'SELECT count(*) AS n FROM recommendation WHERE sender_key = %(k)s AND created_at >= %(w)s',
        dict(k=sender_key, w=week_start(now))).fetchone()['n'])


def allowance(tx, sender_key: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return dict(left=max(0, WEEKLY_LIMIT - _used(tx, sender_key, now)), **{'from': next_week_day()})


def _refused_row(tx, base: dict) -> None:
    """A refusal, counted against the sender's week and nothing else: no
    address, and a key that matches nobody."""
    tx.execute(
        """INSERT INTO recommendation (sender_person_id, sender_key, sender_first_name,
                                       recipient_key, status, flag_reason)
           VALUES (%(sp)s, %(sk)s, %(sf)s, %(rk)s, 'rejected', 'refused')""",
        dict(base, rk=f'refused:{secrets.token_hex(16)}'))


def recommend(tx, *, sender: dict, email: str, note: Optional[str],
              now: Optional[datetime] = None) -> dict:
    """`sender` is {person_id, first_name, key, normalized_email}: a member
    (person_id set) or a visitor (None). Answers {state: 'sent'} whatever
    happens next, or raises MatchmakerError('limit', 429, {'from': 'Monday'})
    at 5 in the sender's week (5a.5)."""
    from service.leads import clean_email
    now = now or datetime.now(timezone.utc)
    cleaned = clean_email(email)
    if cleaned is None:
        raise MatchmakerError('bad_email', 400)
    address, normalised = cleaned
    text = clean_note(note, default=DEFAULT_NOTE)
    # Read committed (the route's): after the lock, each count sees what
    # the sender's other request just committed.
    tx.execute("SELECT pg_advisory_xact_lock(hashtext('mm-rec:' || %(k)s))", dict(k=sender['key']))
    if _used(tx, sender['key'], now) >= WEEKLY_LIMIT:
        raise MatchmakerError('limit', 429, {'from': next_week_day()})
    key = address_key(normalised)
    is_member = tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                           dict(ne=normalised)).fetchone() is not None
    before = tx.execute("SELECT 1 FROM recommendation WHERE recipient_key = %(k)s AND status <> 'rejected'",
                        dict(k=key)).fetchone() is not None
    own = normalised == sender.get('normalized_email')
    base = dict(sp=sender.get('person_id'), sk=sender['key'], sf=sender.get('first_name'))
    if is_member or before or own:
        _refused_row(tx, base)
        return dict(state='sent')
    code = None
    if sender.get('person_id') is not None:
        from service.referrals import mint_person_code
        code = mint_person_code(tx, sender['person_id'])
    flag = note_flag(text) if text != DEFAULT_NOTE else None
    # Two senders naming the same address at once: the unique index on
    # recipient_key lets one through, and the other is a repeat.
    tx.execute('SAVEPOINT mm_recommend_row')
    try:
        rec_id = tx.execute(
            """INSERT INTO recommendation (sender_person_id, sender_key, sender_first_name,
                                           recipient_email, recipient_key, note, referral_code,
                                           status, flag_reason)
               VALUES (%(sp)s, %(sk)s, %(sf)s, %(e)s, %(rk)s, %(n)s, %(c)s, %(st)s, %(f)s)
               RETURNING id""",
            dict(base, e=address, rk=key, n=text, c=code, st='held' if flag else 'queued',
                 f=flag)).fetchone()['id']
    except psycopg.errors.UniqueViolation:
        tx.execute('ROLLBACK TO SAVEPOINT mm_recommend_row')
        _refused_row(tx, base)
        return dict(state='sent')
    tx.execute('RELEASE SAVEPOINT mm_recommend_row')
    if not flag:
        send_recommendation(tx, rec_id)
    return dict(state='sent')


def send_recommendation(tx, rec_id: int) -> Optional[int]:
    """Queue the recommendation's one email (mm_recommend, campaign_id the
    row's id) and mark it sent. Used here and by the approval in
    Moderation > Text."""
    from service.campaigns import outbox
    from service.config import WEB_BASE_URL
    from service.matchmaker import mail
    if not mail.campaign_on(mail.CAMPAIGN_RECOMMEND):
        return None
    row = tx.execute("SELECT * FROM recommendation WHERE id = %(i)s AND status IN ('queued', 'held') "
                     "AND recipient_email IS NOT NULL", dict(i=rec_id)).fetchone()
    if row is None:
        return None
    cta = f"{WEB_BASE_URL}/i/{row['referral_code']}" if row['referral_code'] else f'{WEB_BASE_URL}/'

    def go():
        subject, body = mail.recommend_email(row['sender_first_name'] or 'Someone', row['note'], cta)
        out = outbox.enqueue_for_recommendation(
            tx, campaign=mail.CAMPAIGN_RECOMMEND, campaign_id=str(rec_id), recommendation_id=rec_id,
            email=row['recipient_email'], subject=subject, html=body, from_addr=mail.FROM_ADDR)
        tx.execute("UPDATE recommendation SET status = 'sent', sent_at = NOW() WHERE id = %(i)s",
                   dict(i=rec_id))
        return out
    return mail.guarded(tx, 'mm_recommend', go)
