"""The single's mentor (TEC-1845, sections 6 and 8): invite, remove, and
share one conversation at a time.

"A mentor sees only what the single chooses to share, and the other
person is always told." A mentor is a role on mentor_account, never a
person row, so no search or count can include them. One mentor per single.

What a mentor reads (owner's answer, 21 Oct 2026, item 30): only messages
sent after the single shares the conversation, never the history before
it. Each share keeps its start time (shared_conversation.shared_at), and
service/matchmaker/mentor_view.py reads nothing older. The other member is
told in both people's views: the header notice and a line in the
conversation where sharing began and stopped (sharing()). No push or email
goes to the other member when a share starts: the plan sends none.

Every function takes the caller's transaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from service.matchmaker import MatchmakerError, first_name, is_uuid

INVITE_TTL = timedelta(days=14)
RELATIONS = ('parent', 'elder', 'mentor', 'friend')


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def mentor_display_name(email: str) -> str:
    """Until a mentor can give a first name (plan item 18): the part of the
    address before the @, capitalised."""
    local = (email or '').split('@', 1)[0].replace('.', ' ').replace('_', ' ').strip()
    word = local.split()[0] if local.split() else 'Mentor'
    return word[:1].upper() + word[1:].lower()


def _live_link(tx, single_id: int, *, lock: bool = False) -> Optional[dict]:
    row = tx.execute(
        'SELECT * FROM mentor_link WHERE single_person_id = %(s)s AND revoked_at IS NULL'
        + (' FOR UPDATE' if lock else ''), dict(s=single_id)).fetchone()
    return dict(row) if row else None


def state(tx, single_id: int) -> dict:
    """6.1 to 6.5: none, invited or confirmed, and what is shared."""
    link = _live_link(tx, single_id)
    if link is None:
        return dict(state='none', shared=[])
    out = dict(state='confirmed' if link['confirmed_at'] else 'invited', email=link['mentor_email'],
               relation=link['relation'], shared=[])
    if link['confirmed_at']:
        out.update(first_name=mentor_display_name(link['mentor_email']),
                   since=link['confirmed_at'].date().isoformat())
        out['shared'] = [dict(uuid=r['uuid'], first_name=first_name(r['name']),
                              shared_since=r['shared_at'].date().isoformat())
                         for r in tx.execute(
            """SELECT p.uuid::text AS uuid, p.name, sc.shared_at FROM shared_conversation sc
                 JOIN person p ON p.id = sc.other_person_id
                WHERE sc.mentor_link_id = %(l)s AND sc.revoked_at IS NULL
                ORDER BY sc.shared_at""", dict(l=link['id'])).fetchall()]
    return out


def _single(tx, single_id: int) -> dict:
    return dict(tx.execute(
        """SELECT p.name, p.normalized_email, g.name AS gender FROM person p
             LEFT JOIN gender g ON g.id = p.gender_id WHERE p.id = %(i)s""",
        dict(i=single_id)).fetchone())


def invite(tx, single_id: int, email: str, relation: str, now: Optional[datetime] = None) -> dict:
    """6.1: one live link per single; the invitation by email (6.1 of the
    emails). The mentor accepts from the link, which proves the address."""
    from service.leads import clean_email, new_token
    now = _now(now)
    if relation not in RELATIONS:
        raise MatchmakerError('bad_relation', 400)
    cleaned = clean_email(email)
    if cleaned is None:
        raise MatchmakerError('bad_email', 400)
    address, normalised = cleaned
    me = _single(tx, single_id)
    if normalised == me['normalized_email']:
        raise MatchmakerError('bad_email', 400)
    tx.execute("SELECT pg_advisory_xact_lock(hashtext('mm-mentor:' || %(s)s::text))", dict(s=single_id))
    if _live_link(tx, single_id) is not None:
        raise MatchmakerError('has_mentor', 409)
    token, hashed = new_token()
    link_id = tx.execute(
        """INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, relation,
                                    invite_token_hash, invite_expires_at)
           VALUES (%(s)s, %(e)s, %(ne)s, %(r)s, %(h)s, %(x)s) RETURNING id""",
        dict(s=single_id, e=address, ne=normalised, r=relation, h=hashed, x=now + INVITE_TTL)).fetchone()['id']
    _queue_invite(tx, link_id, address, first_name(me['name']), me['gender'], token)
    return state(tx, single_id)


def _queue_invite(tx, link_id: int, address: str, single_first: str, gender: Optional[str],
                  token: str) -> Optional[int]:
    from emails.base import is_suppressed_send
    from service.campaigns import outbox
    from service.matchmaker import mail
    if not mail.campaign_on(mail.CAMPAIGN_MENTOR_INVITE) or is_suppressed_send(address):
        return None

    def go():
        from emails import your_ahavah_line
        subject, body = mail.mentor_invite_email(single_first, mail.pronoun_for(gender),
                                                 mail.mentor_accept_url(token),
                                                 your_ahavah=your_ahavah_line.for_address(tx, address))
        return outbox.enqueue_for_mentor_link(
            tx, campaign=mail.CAMPAIGN_MENTOR_INVITE, campaign_id=str(link_id), mentor_link_id=link_id,
            email=address, subject=subject, html=body, from_addr=mail.FROM_ADDR)
    return mail.guarded(tx, 'mm_mentor_invite', go)


def cancel_invite(tx, single_id: int, now: Optional[datetime] = None) -> dict:
    """6.3's "Cancel invitation"."""
    link = _live_link(tx, single_id, lock=True)
    if link is None or link['confirmed_at'] is not None:
        raise MatchmakerError('no_invite', 404)
    tx.execute('UPDATE mentor_link SET revoked_at = %(now)s WHERE id = %(i)s', dict(now=_now(now), i=link['id']))
    return state(tx, single_id)


def remove(tx, single_id: int, now: Optional[datetime] = None) -> dict:
    """6.6, 6.7: "They will lose access straight away." The link and every
    live share end at once, and the mentor's notes about this single's
    matches are deleted."""
    now = _now(now)
    link = _live_link(tx, single_id, lock=True)
    if link is None:
        raise MatchmakerError('no_mentor', 404)
    tx.execute('UPDATE mentor_link SET revoked_at = %(now)s WHERE id = %(i)s', dict(now=now, i=link['id']))
    tx.execute('UPDATE shared_conversation SET revoked_at = %(now)s WHERE mentor_link_id = %(i)s '
               'AND revoked_at IS NULL', dict(now=now, i=link['id']))
    if link['mentor_account_id'] is not None:
        tx.execute('DELETE FROM mentor_note WHERE mentor_account_id = %(m)s AND single_person_id = %(s)s',
                   dict(m=link['mentor_account_id'], s=single_id))
    return state(tx, single_id)


def _other(tx, uuid: str) -> Optional[dict]:
    if not is_uuid(uuid):
        return None
    row = tx.execute('SELECT id, uuid::text AS uuid, name, no_mentor_shared_matches FROM person '
                     'WHERE uuid = %(u)s::uuid', dict(u=uuid)).fetchone()
    return dict(row) if row else None


def _matched(tx, a: int, b: int) -> bool:
    return tx.execute(
        """SELECT EXISTS (SELECT 1 FROM ahavah_match m
                           WHERE m.user_a_id = LEAST(%(a)s::int, %(b)s::int)
                             AND m.user_b_id = GREATEST(%(a)s::int, %(b)s::int))
                  AND NOT is_blocked_pair(%(a)s, %(b)s) AS ok""", dict(a=a, b=b)).fetchone()['ok']


def share(tx, single_id: int, other_uuid: str, now: Optional[datetime] = None) -> dict:
    """6.8: share the conversation with this match. The share's start time
    is kept: the mentor reads only messages sent after it."""
    now = _now(now)
    other = _other(tx, other_uuid)
    if other is None or not _matched(tx, single_id, other['id']):
        raise MatchmakerError('not_found', 404)
    link = _live_link(tx, single_id, lock=True)
    if link is None or link['confirmed_at'] is None:
        raise MatchmakerError('no_mentor', 409)
    if other['no_mentor_shared_matches']:
        raise MatchmakerError('cannot_share', 409)
    tx.execute(
        """INSERT INTO shared_conversation (single_person_id, other_person_id, other_person_uuid,
                                            mentor_link_id, shared_at)
           VALUES (%(s)s, %(o)s, %(u)s::uuid, %(l)s, %(now)s)
           ON CONFLICT (single_person_id, other_person_id) WHERE revoked_at IS NULL DO NOTHING""",
        dict(s=single_id, o=other['id'], u=other['uuid'], l=link['id'], now=now))
    return dict(shared=True)


def unshare(tx, single_id: int, other_uuid: str, now: Optional[datetime] = None) -> dict:
    """6.9: "Stop sharing"."""
    other = _other(tx, other_uuid)
    if other is None:
        raise MatchmakerError('not_found', 404)
    tx.execute('UPDATE shared_conversation SET revoked_at = %(now)s WHERE single_person_id = %(s)s '
               'AND other_person_id = %(o)s AND revoked_at IS NULL',
               dict(now=_now(now), s=single_id, o=other['id']))
    return dict(shared=False)


# The words both people see (8.1, 8.3, 8.4 and the owner's answer to item
# 30). Every line but 8.1, 8.3 and 8.4 is a NEW LINE, for /copy-pass and
# the owner before launch.

def _notice(by_me: bool, by_them: bool, their_first: str) -> Optional[str]:
    if by_them:
        return f'{their_first}’s mentor can read this conversation'  # 8.1
    if by_me:
        return 'Shared with your mentor'  # 8.3
    return None


def _line(kind: str, by: str, their_first: str) -> str:
    if kind == 'shared':
        if by == 'them':
            # NEW LINE (owner's answer, item 30), for /copy-pass.
            return (f'{their_first} shared this conversation with their mentor. '
                    'Messages from now on can be read by them.')
        return 'You shared this conversation with your mentor. They can read messages from now on.'  # NEW LINE
    if by == 'them':
        return f'{their_first} stopped sharing this conversation'  # 8.4
    return 'You stopped sharing this conversation'  # NEW LINE


def sharing(tx, viewer_id: int, other_uuid: str) -> dict:
    """For either person of the pair: who shares, the header notice and the
    lines for the conversation where sharing began and stopped, by time."""
    other = _other(tx, other_uuid)
    empty = dict(shared_by_me=False, shared_by_them=False, their_first_name=None, notice=None, events=[])
    if other is None or other['id'] == viewer_id:
        return empty
    blocked = tx.execute('SELECT is_blocked_pair(%(a)s, %(b)s) AS b',
                         dict(a=viewer_id, b=other['id'])).fetchone()['b']
    if blocked:
        return empty
    their_first = first_name(other['name'])
    rows = tx.execute(
        """SELECT single_person_id, shared_at, revoked_at FROM shared_conversation
            WHERE (single_person_id = %(me)s AND other_person_id = %(o)s)
               OR (single_person_id = %(o)s AND other_person_id = %(me)s)""",
        dict(me=viewer_id, o=other['id'])).fetchall()
    events = []
    by_me = by_them = False
    for r in rows:
        by = 'me' if r['single_person_id'] == viewer_id else 'them'
        events.append(dict(kind='shared', by=by, at=r['shared_at']))
        if r['revoked_at'] is None:
            by_me = by_me or by == 'me'
            by_them = by_them or by == 'them'
        else:
            events.append(dict(kind='stopped', by=by, at=r['revoked_at']))
    events.sort(key=lambda e: (e['at'], 0 if e['kind'] == 'shared' else 1))
    for e in events:
        e['line'] = _line(e['kind'], e['by'], their_first)
        e['at'] = e['at'].isoformat()
    return dict(shared_by_me=by_me, shared_by_them=by_them, their_first_name=their_first,
                notice=_notice(by_me, by_them, their_first), events=events)
