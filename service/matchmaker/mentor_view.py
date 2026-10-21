"""The mentor's side (TEC-1845, section 7): signing in, the single's matches
as the single sees them, a private note, and a shared conversation, read
only.

A mentor has no person row and no profile. They sign in first from the
invitation link (it proves the address, once), later with the standard
6-digit code, which leaves a session for the address that /mentor/session
exchanges for a mentor token. The token travels in the X-Mentor-Token
header; only its sha256 is stored, and it lasts SESSION_TTL.

What a mentor reads (owner's answer, 21 Oct 2026, item 30): only the
messages sent after the single shared the conversation, never the history
before it. A message's archive id is its time (microseconds << 8, service/
chat/messagestorage/mam), so the read starts at the live share's
shared_at. Text only; a voice message is a line; no images or
translations. A removed mentor's next call answers access_ended at once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from service.matchmaker import MatchmakerError, first_name, is_uuid

SESSION_TTL = timedelta(days=30)
ENDED_FOR = timedelta(days=30)
PAGE = 50


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def message_text(binary: bytes) -> Optional[str]:
    """The text of a stored chat message (the unpacking antiabuse/
    lodgereport uses), or None when there is none to read."""
    import erlastic
    try:
        text = erlastic.decode(binary)[3][0][3][0][1]
        return text.decode('utf-8') if isinstance(text, bytes) else str(text)
    except Exception:
        return None


def _message_id_at(at: datetime) -> int:
    """The first archive id at or after this instant."""
    micros = int(at.timestamp() * 1_000_000)
    return micros << 8


def _id_time(message_id: int) -> str:
    return datetime.fromtimestamp((message_id >> 8) / 1_000_000, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def _issue(tx, account_id: int, now: datetime) -> dict:
    from service.leads import new_token
    token, hashed = new_token()
    tx.execute('INSERT INTO mentor_session (token_hash, mentor_account_id, expires_at) '
               'VALUES (%(h)s, %(a)s, %(x)s)', dict(h=hashed, a=account_id, x=now + SESSION_TTL))
    tx.execute('UPDATE mentor_account SET last_seen_at = %(now)s WHERE id = %(a)s', dict(now=now, a=account_id))
    return dict(token=token)


def _account_for(tx, email: str, normalized: str) -> int:
    row = tx.execute(
        """INSERT INTO mentor_account (email, normalized_email) VALUES (%(e)s, %(ne)s)
           ON CONFLICT (normalized_email) DO UPDATE SET email = mentor_account.email
           RETURNING id""", dict(e=email, ne=normalized)).fetchone()
    return row['id']


def invitation(tx, token: str, now: Optional[datetime] = None) -> dict:
    """The sign-in page's look at its invitation: {single_first_name, email}."""
    from service.leads import token_hash
    now = _now(now)
    if not isinstance(token, str) or not token:
        raise MatchmakerError('not_found', 404)
    row = tx.execute(
        """SELECT l.*, p.name FROM mentor_link l JOIN person p ON p.id = l.single_person_id
            WHERE l.invite_token_hash = %(h)s AND l.revoked_at IS NULL""",
        dict(h=token_hash(token))).fetchone()
    if row is None:
        raise MatchmakerError('not_found', 404)
    if row['invite_expires_at'] <= now:
        raise MatchmakerError('expired', 410)
    return dict(single_first_name=first_name(row['name']), email=row['mentor_email'])


def start_session(tx, *, invite_token: Optional[str] = None, session_email: Optional[str] = None,
                  now: Optional[datetime] = None) -> dict:
    """{token}. From an invitation link (unexpired, not revoked, used once:
    it confirms the link), or from a signed-in session's address when that
    address has a confirmed live link."""
    from service.leads import clean_email, token_hash
    now = _now(now)
    if invite_token:
        row = tx.execute('SELECT * FROM mentor_link WHERE invite_token_hash = %(h)s FOR UPDATE',
                         dict(h=token_hash(invite_token))).fetchone()
        if row is None or row['revoked_at'] is not None:
            raise MatchmakerError('not_a_mentor', 403)
        if row['invite_expires_at'] <= now:
            raise MatchmakerError('expired', 410)
        account = row['mentor_account_id'] or _account_for(tx, row['mentor_email'],
                                                           row['mentor_normalized_email'])
        tx.execute("""UPDATE mentor_link SET mentor_account_id = %(a)s,
                             confirmed_at = COALESCE(confirmed_at, %(now)s), invite_token_hash = NULL
                       WHERE id = %(i)s""", dict(a=account, now=now, i=row['id']))
        return _issue(tx, account, now)
    cleaned = clean_email(session_email) if session_email else None
    if cleaned is None:
        raise MatchmakerError('not_a_mentor', 403)
    row = tx.execute(
        """SELECT l.mentor_account_id FROM mentor_link l
            WHERE l.mentor_normalized_email = %(ne)s AND l.revoked_at IS NULL
              AND l.confirmed_at IS NOT NULL AND l.mentor_account_id IS NOT NULL
            LIMIT 1""", dict(ne=cleaned[1])).fetchone()
    if row is None:
        raise MatchmakerError('not_a_mentor', 403)
    return _issue(tx, row['mentor_account_id'], now)


def end_session(tx, token: Optional[str]) -> None:
    from service.leads import token_hash
    if token:
        tx.execute('DELETE FROM mentor_session WHERE token_hash = %(h)s', dict(h=token_hash(token)))


def mentor_for(tx, token: Optional[str], now: Optional[datetime] = None) -> dict:
    """{id, email} for a live token; signed_out (401) otherwise."""
    from service.leads import token_hash
    now = _now(now)
    if not token:
        raise MatchmakerError('signed_out', 401)
    row = tx.execute(
        """SELECT a.id, a.email FROM mentor_session s JOIN mentor_account a ON a.id = s.mentor_account_id
            WHERE s.token_hash = %(h)s AND s.expires_at > %(now)s""",
        dict(h=token_hash(token), now=now)).fetchone()
    if row is None:
        raise MatchmakerError('signed_out', 401)
    tx.execute('UPDATE mentor_account SET last_seen_at = %(now)s WHERE id = %(a)s', dict(now=now, a=row['id']))
    return dict(row)


# ---------------------------------------------------------------------------
# What a mentor sees
# ---------------------------------------------------------------------------

def singles(tx, mentor: dict, now: Optional[datetime] = None) -> dict:
    """7.4, 7.5 and 7.12: the singles this mentor serves, and the ones who
    ended it in the last 30 days."""
    now = _now(now)
    live = tx.execute(
        """SELECT p.uuid::text AS uuid, p.name FROM mentor_link l JOIN person p ON p.id = l.single_person_id
            WHERE l.mentor_account_id = %(m)s AND l.confirmed_at IS NOT NULL AND l.revoked_at IS NULL
            ORDER BY l.confirmed_at""", dict(m=mentor['id'])).fetchall()
    ended = tx.execute(
        """SELECT DISTINCT ON (l.single_person_id) p.name FROM mentor_link l
             JOIN person p ON p.id = l.single_person_id
            WHERE l.mentor_account_id = %(m)s AND l.confirmed_at IS NOT NULL
              AND l.revoked_at IS NOT NULL AND l.revoked_at > %(since)s
              AND NOT EXISTS (SELECT 1 FROM mentor_link x WHERE x.single_person_id = l.single_person_id
                                AND x.mentor_account_id = %(m)s AND x.revoked_at IS NULL
                                AND x.confirmed_at IS NOT NULL)
            ORDER BY l.single_person_id, l.revoked_at DESC""",
        dict(m=mentor['id'], since=now - ENDED_FOR)).fetchall()
    return dict(singles=[dict(uuid=r['uuid'], first_name=first_name(r['name'])) for r in live],
                ended=[dict(first_name=first_name(r['name'])) for r in ended])


def _served(tx, mentor: dict, single_uuid: str) -> dict:
    """The single, when this mentor serves them now; access_ended otherwise
    (a removed mentor, another single, a guessed uuid)."""
    if not is_uuid(single_uuid):
        raise MatchmakerError('access_ended', 410)
    row = tx.execute(
        """SELECT p.id, p.name, l.id AS link_id FROM mentor_link l JOIN person p ON p.id = l.single_person_id
            WHERE p.uuid = %(u)s::uuid AND l.mentor_account_id = %(m)s
              AND l.confirmed_at IS NOT NULL AND l.revoked_at IS NULL""",
        dict(u=single_uuid, m=mentor['id'])).fetchone()
    if row is None:
        raise MatchmakerError('access_ended', 410)
    return dict(row)


def _live_share(tx, single_id: int, other_id: int) -> Optional[dict]:
    row = tx.execute('SELECT * FROM shared_conversation WHERE single_person_id = %(s)s '
                     'AND other_person_id = %(o)s AND revoked_at IS NULL', dict(s=single_id, o=other_id)).fetchone()
    return dict(row) if row else None


def matches(tx, mentor: dict, single_uuid: str) -> list[dict]:
    """7.4: the single's matches as the single sees them (Q_LIST_MATCHES,
    run as the single), each saying whether its conversation is shared."""
    from service.decisions import Q_LIST_MATCHES
    single = _served(tx, mentor, single_uuid)
    shared = {r['other_person_uuid'] for r in tx.execute(
        'SELECT other_person_uuid::text AS other_person_uuid FROM shared_conversation '
        'WHERE single_person_id = %(s)s AND revoked_at IS NULL', dict(s=single['id'])).fetchall()}
    return [dict(uuid=r['peer_uuid'], first_name=first_name(r['peer_name']), age=r['peer_age'],
                 photo_uuids=r['peer_photo_uuids'], shared=r['peer_uuid'] in shared)
            for r in tx.execute(Q_LIST_MATCHES, dict(me_id=single['id'])).fetchall()]


def _match(tx, single_id: int, match_uuid: str) -> dict:
    if not is_uuid(match_uuid):
        raise MatchmakerError('not_found', 404)
    row = tx.execute(
        """SELECT p.id, p.name, p.about,
                  (SELECT EXTRACT(YEAR FROM AGE(p.date_of_birth))::int WHERE p.show_my_age) AS age,
                  (SELECT p.location_short_friendly WHERE p.show_my_location) AS place,
                  COALESCE((SELECT json_agg(ph.uuid ORDER BY ph.position) FROM photo ph
                             WHERE ph.person_id = p.id AND ph.moderation_status = 'approved'),
                           '[]'::json)::jsonb AS photo_uuids
             FROM person p
            WHERE p.uuid = %(u)s::uuid AND p.activated
              AND EXISTS (SELECT 1 FROM ahavah_match m
                           WHERE m.user_a_id = LEAST(%(s)s, p.id) AND m.user_b_id = GREATEST(%(s)s, p.id))
              AND NOT is_blocked_pair(%(s)s, p.id)""",
        dict(u=match_uuid, s=single_id)).fetchone()
    if row is None:
        raise MatchmakerError('not_found', 404)
    return dict(row)


def _note(tx, mentor_id: int, single_id: int, about_id: int) -> Optional[str]:
    row = tx.execute('SELECT note FROM mentor_note WHERE mentor_account_id = %(m)s AND single_person_id = %(s)s '
                     'AND about_person_id = %(a)s', dict(m=mentor_id, s=single_id, a=about_id)).fetchone()
    return row['note'] if row else None


def match_detail(tx, mentor: dict, single_uuid: str, match_uuid: str) -> dict:
    """7.7 and 7.9: the match as the single sees them, and the mentor's own note."""
    single = _served(tx, mentor, single_uuid)
    m = _match(tx, single['id'], match_uuid)
    out = dict(first_name=first_name(m['name']), place=m['place'], photo_uuids=m['photo_uuids'],
               about=m['about'], shared=_live_share(tx, single['id'], m['id']) is not None,
               note=_note(tx, mentor['id'], single['id'], m['id']))
    if m['age'] is not None:
        out['age'] = m['age']
    return out


def conversation(tx, mentor: dict, single_uuid: str, match_uuid: str, before: Optional[int] = None) -> dict:
    """7.10: the shared conversation from the single's archive, oldest
    first, 50 at a time (`before` an id from an earlier page). Only what was
    sent after the share began. not_shared (403) once sharing stops."""
    single = _served(tx, mentor, single_uuid)
    m = _match(tx, single['id'], match_uuid)
    share = _live_share(tx, single['id'], m['id'])
    if share is None:
        raise MatchmakerError('not_shared', 403)
    rows = tx.execute(
        """SELECT id, direction, message, audio_uuid FROM mam_message
            WHERE person_id = %(s)s AND split_part(remote_bare_jid, '@', 1) = %(u)s
              AND id >= %(from_id)s
              AND (%(before)s::BIGINT IS NULL OR id < %(before)s::BIGINT)
            ORDER BY id DESC LIMIT %(n)s""",
        dict(s=single['id'], u=match_uuid, from_id=_message_id_at(share['shared_at']),
             before=before, n=PAGE)).fetchall()
    messages = []
    for r in reversed(rows):
        voice = bool(r['audio_uuid'])
        item = {'id': str(r['id']), 'from': 'single' if r['direction'] == 'O' else 'match',
                'voice': voice, 'at': _id_time(r['id'])}
        if not voice:
            text = message_text(bytes(r['message']))
            if text is None:
                continue
            item['text'] = text
        messages.append(item)
    return dict(messages=messages, single_first_name=first_name(single['name']),
                match_first_name=first_name(m['name']), shared_since=share['shared_at'].isoformat())


def save_note(tx, mentor: dict, single_uuid: str, match_uuid: str, note: Optional[str]) -> None:
    """7.7's note, 1 to 1000 characters; an empty note deletes it."""
    from service.matchmaker.recommend import clean_note
    single = _served(tx, mentor, single_uuid)
    m = _match(tx, single['id'], match_uuid)
    if note is None or not str(note).strip():
        tx.execute('DELETE FROM mentor_note WHERE mentor_account_id = %(m)s AND single_person_id = %(s)s '
                   'AND about_person_id = %(a)s', dict(m=mentor['id'], s=single['id'], a=m['id']))
        return
    text = clean_note(note, 1000)
    tx.execute(
        """INSERT INTO mentor_note (mentor_account_id, single_person_id, about_person_id, note)
           VALUES (%(m)s, %(s)s, %(a)s, %(n)s)
           ON CONFLICT (mentor_account_id, single_person_id, about_person_id)
           DO UPDATE SET note = EXCLUDED.note, updated_at = NOW()""",
        dict(m=mentor['id'], s=single['id'], a=m['id'], n=text))


def note_for_single(tx, single_id: int, match_uuid: str) -> Optional[str]:
    """8.5: the single's current mentor's note about this match. Never the
    match's to see."""
    if not is_uuid(match_uuid):
        return None
    row = tx.execute(
        """SELECT n.note FROM mentor_note n
             JOIN mentor_link l ON l.mentor_account_id = n.mentor_account_id
                               AND l.single_person_id = n.single_person_id
                               AND l.revoked_at IS NULL AND l.confirmed_at IS NOT NULL
             JOIN person p ON p.id = n.about_person_id
            WHERE n.single_person_id = %(s)s AND p.uuid = %(u)s::uuid""",
        dict(s=single_id, u=match_uuid)).fetchone()
    return row['note'] if row else None
