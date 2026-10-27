"""Your Ahavah, the light sign-in (TEC-1845; ahavah-web docs/plans/
2026-10-22-in-app-entry-and-sign-up.md, section 5, release 4).

For people who use Ahavah without being members: organisers, mentors,
parents and friends who recommend a single, and gathering guests. One
proved address opens what is held under it, and lets them delete all of
it. "Start a matchmaking profile" is the web's: sign-up with the address
filled in, after which the finish-sign-up steps bring across what the
address holds (service/person, post_finish_onboarding).

The sign-in is an ADDRESS session (migration 0085), kept apart from the
member's duo_session and from the half-finished sign-up record:

  request_code  a 6-digit code to the address, by the same code email
                members get; answers the same handle whatever happens, so
                the answer never says whether the address exists
  check_code    the code and the handle -> an address token, valid
                SESSION_TTL, sent back as X-Address-Token. It is never a
                bearer token: the member routes read duo_session only, so
                it opens none of them
  held          what the address holds: gatherings hosted, places,
                singles mentored (first name only), saved Together
                results, a visitor alert and recommendations sent (date
                and count only). Never a member's name (but a mentored
                single's first name), photo or profile; never a guest's
                name; never a venue
  erase         everything under the address, by the account erase code
                (service/hard_delete), and ends the session

Dark until launch: while light_sign_in or matchmaker_live is off
(service/campaigns/switches.py) every /your-ahavah route answers 404 and
/matchmaker/status says light_sign_in false.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from service.campaigns.switches import enabled

CODE_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(minutes=60)
MAX_ATTEMPTS = 5
# Rows are kept a day past their code or session, then the lead retention
# cron deletes them, address and all.
KEEP_AFTER = timedelta(days=1)
# What one section lists at most; the web is told when there is more.
SECTION_MAX = 50


class YourAhavahError(Exception):
    """A refusal the route answers as {error: reason} with this status."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def on() -> bool:
    """The light sign-in is open. It is reported on /matchmaker/status, so
    it counts only once the matchmaker is live."""
    return enabled('matchmaker_live') and enabled('light_sign_in')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _code_hash(request_token: str, code: str) -> str:
    return _sha(f'{request_token}:{code}')


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def send_code(email: str, code: str) -> None:
    """The members' own sign-in code email, reused: the brief keeps the
    code step as it is, so there is nothing new to learn. Threaded and
    best effort, as person._send_otp is."""
    from service.person import _send_otp
    _send_otp(email, code)


def request_code(tx, email: str, *, refused: bool = False,
                 now: Optional[datetime] = None) -> tuple[str, Optional[str]]:
    """A new code for the address. Returns (handle, code): the handle goes
    to the web whatever happens; the code is None when nothing should be
    mailed (a refused caller or a bad address), and the caller mails it
    after the commit otherwise. A refused or malformed request still gets a
    handle, which no code will ever match."""
    from service.leads import clean_email
    handle = secrets.token_urlsafe(24)
    cleaned = clean_email(email)
    if refused or cleaned is None:
        return handle, None
    address, normalised = cleaned
    now = _now(now)
    code = f'{secrets.randbelow(10 ** 6):06d}'
    tx.execute(
        """INSERT INTO address_session (email, normalized_email, request_token_hash, code_hash,
                                        code_expires_at)
           VALUES (%(e)s, %(ne)s, %(h)s, %(c)s, %(x)s)""",
        dict(e=address, ne=normalised, h=_sha(handle), c=_code_hash(handle, code), x=now + CODE_TTL))
    return handle, code


def check_code(tx, handle: object, code: object, now: Optional[datetime] = None) -> dict:
    """The code the address received -> {address_token, expires_at}. A
    wrong code counts against the handle (5 and it dies) and answers
    {error: 'wrong_code'} rather than raising, so the caller's transaction
    commits the count; an unknown, lapsed, used or dead handle raises
    'expired'. A code works once."""
    now = _now(now)
    if not isinstance(handle, str) or not 16 <= len(handle) <= 64:
        raise YourAhavahError('expired', 401)
    row = tx.execute(
        """SELECT id, code_hash, code_expires_at, code_attempts FROM address_session
            WHERE request_token_hash = %(h)s FOR UPDATE""", dict(h=_sha(handle))).fetchone()
    if (row is None or row['code_hash'] is None or row['code_expires_at'] <= now
            or row['code_attempts'] >= MAX_ATTEMPTS):
        raise YourAhavahError('expired', 401)
    if not isinstance(code, str) or not secrets.compare_digest(row['code_hash'], _code_hash(handle, code)):
        tx.execute('UPDATE address_session SET code_attempts = code_attempts + 1 WHERE id = %(i)s',
                   dict(i=row['id']))
        return dict(error='wrong_code')
    token = secrets.token_urlsafe(32)
    expires = now + SESSION_TTL
    tx.execute(
        """UPDATE address_session SET code_hash = NULL, session_token_hash = %(t)s,
                                      session_expires_at = %(x)s
            WHERE id = %(i)s""", dict(t=_sha(token), x=expires, i=row['id']))
    return dict(address_token=token, expires_at=_iso(expires))


def address_for(tx, token: object, now: Optional[datetime] = None) -> dict:
    """{email, normalized_email, expires_at} of a live address token, or
    'expired' (401)."""
    if not isinstance(token, str) or not 16 <= len(token) <= 64:
        raise YourAhavahError('expired', 401)
    row = tx.execute(
        """SELECT email, normalized_email, session_expires_at FROM address_session
            WHERE session_token_hash = %(h)s AND session_expires_at > %(now)s""",
        dict(h=_sha(token), now=_now(now))).fetchone()
    if row is None:
        raise YourAhavahError('expired', 401)
    return dict(row)


def end_session(tx, token: object) -> None:
    if isinstance(token, str) and 16 <= len(token) <= 64:
        tx.execute('DELETE FROM address_session WHERE session_token_hash = %(h)s', dict(h=_sha(token)))


def is_member(tx, email: str, normalized_email: str) -> bool:
    """The address belongs to a member, matched as the members' sign-in
    matches a session to its person (service.person, Q_INSERT_DUO_SESSION)."""
    from service.person import normalize_email
    nes = sorted({normalized_email, normalize_email(email)})
    return tx.execute('SELECT 1 FROM person WHERE normalized_email = ANY(%(n)s) LIMIT 1',
                      dict(n=nes)).fetchone() is not None


def start_profile(tx, token: object, *, source: Optional[str] = None, inviter_code: Optional[str] = None,
                  now: Optional[datetime] = None) -> dict:
    """"Start a matchmaking profile" (design 4.2): the address was proved a
    moment ago, so no second code. The address session is used up first, so
    a token starts one sign-up however often it is sent; a refusal raises,
    the caller's transaction rolls back and the session stays. Then the
    members' own sign-up makes and signs in the session
    (service.person.sign_up_proved_address), and the answer is what
    /request-otp and a right code at /check-otp give: {session_token,
    onboarded, ...}. The finish-sign-up steps then bring across what the
    address holds, by address, as after a code.

    'expired' (401) for a lapsed or unknown session, 'member' (409) for an
    address that belongs to a member (they sign in instead), 'refused'
    (403) when the address may not sign up now (a ban, a bad domain)."""
    from service.person import sign_up_proved_address
    if not isinstance(token, str) or not 16 <= len(token) <= 64:
        raise YourAhavahError('expired', 401)
    who = tx.execute(
        """DELETE FROM address_session
            WHERE session_token_hash = %(h)s AND session_expires_at > %(now)s
           RETURNING email, normalized_email""", dict(h=_sha(token), now=_now(now))).fetchone()
    if who is None:
        raise YourAhavahError('expired', 401)
    if is_member(tx, who['email'], who['normalized_email']):
        raise YourAhavahError('member', 409)
    out = sign_up_proved_address(tx, who['email'], source=source, inviter_code=inviter_code)
    if out is None:
        raise YourAhavahError('refused', 403)
    return out


# ---------------------------------------------------------------------------
# What the address holds
# ---------------------------------------------------------------------------

_Q_ORGANISER = """
    SELECT id, name, approved_at IS NOT NULL AS approved FROM organiser
     WHERE normalized_email = %(ne)s AND kind <> 'ahavah'
"""

# The organiser's gatherings, every state, with the confirmed going count.
# Never a guest.
_Q_HOSTED = """
    SELECT e.slug, e.title, e.starts_at, e.ends_at, e.tz, e.tz_label, e.mode, e.status,
           e.paused_at IS NOT NULL AS paused,
           COALESCE(SUM(r.party_size) FILTER (WHERE r.status = 'going' AND r.confirmed_at IS NOT NULL
                                               AND r.erased_at IS NULL), 0)::int AS going
      FROM event e LEFT JOIN event_rsvp r ON r.event_id = e.id
     WHERE e.organiser_id = %(o)s
     GROUP BY e.id
     ORDER BY e.starts_at DESC, e.id DESC
     LIMIT %(n)s
"""

# Places, as the member's own list keeps them (service/events/rsvp.py):
# confirmed and not erased, on a gathering the public may find or one that
# was cancelled. Public fields only: never the venue or the call link.
_Q_PLACES = """
    SELECT r.status, r.party_size, e.slug, e.title, e.starts_at, e.ends_at, e.tz, e.tz_label,
           e.mode, e.city, e.country, e.status AS event_status
      FROM event_rsvp r JOIN event e ON e.id = r.event_id
     WHERE r.normalized_email = %(ne)s AND r.erased_at IS NULL AND r.confirmed_at IS NOT NULL
       AND e.status IN ('published', 'cancelled') AND e.paused_at IS NULL
     ORDER BY e.starts_at DESC, r.id DESC
     LIMIT %(n)s
"""

# Singles the address mentors: a confirmed, live link, to its account or
# its address. First name only.
_Q_MENTORING = """
    SELECT p.name, l.relation, l.confirmed_at
      FROM mentor_link l
      JOIN person p ON p.id = l.single_person_id
      LEFT JOIN mentor_account a ON a.id = l.mentor_account_id
     WHERE (l.mentor_normalized_email = %(ne)s OR a.normalized_email = %(ne)s)
       AND l.confirmed_at IS NOT NULL AND l.revoked_at IS NULL
       AND p.deletion_requested_at IS NULL
     ORDER BY l.confirmed_at, l.id
     LIMIT %(n)s
"""

# Together sessions saved with the address: an owner's that was claimed
# with it, or a guest's seat saved with it. Not deleted ones.
_Q_RESULTS = """
    SELECT s.uuid::text AS session_id, s.kind, s.mode, 'owner' AS seat,
           s.claimed_at AS saved_at, s.completed_at, s.id AS session_pk, NULL::bigint AS player_id
      FROM tool_session s
     WHERE s.owner_normalized_email = %(ne)s AND s.claimed_at IS NOT NULL AND s.deleted_at IS NULL
    UNION ALL
    SELECT s.uuid::text, s.kind, s.mode, 'guest', p.created_at, s.completed_at, s.id, p.id
      FROM tool_player p JOIN tool_session s ON s.id = p.session_id
     WHERE p.seat = 'guest' AND p.normalized_email = %(ne)s AND p.removed_at IS NULL
       AND s.deleted_at IS NULL
     ORDER BY saved_at DESC
     LIMIT %(n)s
"""

_Q_ALERT = """
    SELECT a.confirmed_at, a.active, a.paused_at, a.criteria, a.created_at
      FROM match_alert a JOIN lead l ON l.id = a.lead_id
     WHERE l.normalized_email = %(ne)s AND a.person_id IS NULL
     ORDER BY a.created_at DESC
     LIMIT 1
"""

# Every recommendation the address made, whatever became of it, by day: a
# count of what the sender sent, so it can say nothing about the single
# (not even that one was a member and so never mailed).
_Q_RECOMMENDATIONS = """
    SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*)::int AS n
      FROM recommendation WHERE sender_key = %(k)s
     GROUP BY 1 ORDER BY 1 DESC
     LIMIT %(n)s
"""


def _headline(tx, r: dict) -> Optional[dict]:
    """A saved result's one line (service.tools.sessions.headline): never
    an answer, never the other player."""
    from service.tools.sessions import headline
    return headline(tx, r['session_pk'], r['mode'], r['seat'], r['player_id'], r['completed_at'] is not None)


def held(tx, normalized_email: str, now: Optional[datetime] = None) -> dict:
    """Everything the address holds, section by section. An address that
    holds nothing gets the same shape with every section empty."""
    from service.matchmaker import address_key, first_name
    now = _now(now)
    ne = normalized_email
    n = SECTION_MAX
    member = tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                        dict(ne=ne)).fetchone() is not None

    organiser = tx.execute(_Q_ORGANISER, dict(ne=ne)).fetchone()
    hosting: list[dict] = []
    if organiser is not None:
        for e in tx.execute(_Q_HOSTED, dict(o=organiser['id'], n=n)).fetchall():
            hosting.append(dict(
                slug=e['slug'], title=e['title'], starts_at=_iso(e['starts_at']), ends_at=_iso(e['ends_at']),
                tz=e['tz'], tz_label=e['tz_label'], mode=e['mode'], status=e['status'],
                paused=bool(e['paused']), ended=e['ends_at'] <= now, going=e['going']))

    places = [dict(slug=r['slug'], title=r['title'], starts_at=_iso(r['starts_at']), ends_at=_iso(r['ends_at']),
                   tz=r['tz'], tz_label=r['tz_label'], mode=r['mode'], city=r['city'], country=r['country'],
                   state=r['status'], party_size=r['party_size'], cancelled=r['event_status'] == 'cancelled',
                   ended=r['ends_at'] <= now)
              for r in tx.execute(_Q_PLACES, dict(ne=ne, n=n)).fetchall()]

    mentoring = [dict(first_name=first_name(r['name']), relation=r['relation'], since=_iso(r['confirmed_at']))
                 for r in tx.execute(_Q_MENTORING, dict(ne=ne, n=n)).fetchall()]

    results = []
    for r in tx.execute(_Q_RESULTS, dict(ne=ne, n=n)).fetchall():
        r = dict(r)
        results.append(dict(session_id=r['session_id'], kind=r['kind'], mode=r['mode'], seat=r['seat'],
                            saved_at=_iso(r['saved_at']), completed=r['completed_at'] is not None,
                            result=_headline(tx, r)))

    a = tx.execute(_Q_ALERT, dict(ne=ne)).fetchone()
    alert = None
    if a is not None:
        c = a['criteria'] or {}
        alert = dict(confirmed=a['confirmed_at'] is not None, active=bool(a['active']) and a['paused_at'] is None,
                     age_min=c.get('age_min'), age_max=c.get('age_max'), region=c.get('region'),
                     created_at=_iso(a['created_at']))

    recommendations = [dict(date=r['day'].isoformat(), count=r['n'])
                       for r in tx.execute(_Q_RECOMMENDATIONS, dict(k=address_key(ne), n=n)).fetchall()]

    return dict(
        member=member,
        organiser=(dict(name=organiser['name'], approved=bool(organiser['approved']))
                   if organiser is not None else None),
        hosting=hosting, places=places, mentoring=mentoring, results=results, alert=alert,
        recommendations=recommendations,
        empty=not (organiser or places or mentoring or results or alert or recommendations))


# ---------------------------------------------------------------------------
# Delete everything
# ---------------------------------------------------------------------------

def erase(tx, email: str, normalized_email: str) -> list[str]:
    """Everything under the address, by the account erase code: Together
    sessions and seats, RSVPs, organisers with their gatherings (guests of
    one still to come hear it is cancelled), the matchmaker's data (mentor
    links and account, recommendations to and from it), leads and their
    once-only invitation record, waitlist, beta and referral rows, a
    half-finished sign-up with its photos, and every address session.
    Refused for a member's address ('member', 409): that is the account's
    own deletion, in Settings. Returns the cover keys for
    service.hard_delete.delete_covers once the caller commits."""
    from service.hard_delete import (Q_DELETE_BETA_SIGNUP_OF, Q_DELETE_EVENT_DATA_OF, Q_DELETE_JOIN_INVITES_OF,
                                     Q_DELETE_LEADS_OF, Q_DELETE_MATCHMAKER_DATA_OF, Q_DELETE_TOOL_DATA_OF,
                                     Q_DELETE_WAITLIST_OF, erase_hosting, matchmaker_keys)
    from service.referrals import Q_PURGE_REFERRALS_OF
    ne = normalized_email
    if tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                  dict(ne=ne)).fetchone() is not None:
        raise YourAhavahError('member', 409)
    nes, ids, emails = [ne], [], sorted({email.lower(), ne})
    tx.execute(Q_DELETE_TOOL_DATA_OF, dict(nes=nes, ids=ids))
    tx.execute(Q_DELETE_EVENT_DATA_OF, dict(nes=nes, ids=ids))
    tx.execute(Q_DELETE_MATCHMAKER_DATA_OF, dict(nes=nes, ids=ids, keys=matchmaker_keys(nes)))
    covers = erase_hosting(tx, nes)
    tx.execute(Q_DELETE_LEADS_OF, dict(nes=nes))
    tx.execute(Q_DELETE_JOIN_INVITES_OF, dict(nes=nes))
    tx.execute(Q_DELETE_WAITLIST_OF, dict(emails=emails))
    tx.execute(Q_DELETE_BETA_SIGNUP_OF, dict(emails=emails))
    tx.execute(Q_PURGE_REFERRALS_OF, dict(emails=emails))
    # A half-finished sign-up under the address: its photos go to the CDN
    # cleaner's queue first, then the record and its pending sessions.
    tx.execute("""INSERT INTO undeleted_photo (uuid)
                  SELECT uuid FROM onboardee_photo WHERE lower(email) = ANY(%(e)s)
                  ON CONFLICT DO NOTHING""", dict(e=emails))
    tx.execute('DELETE FROM onboardee WHERE lower(email) = ANY(%(e)s)', dict(e=emails))
    tx.execute('DELETE FROM duo_session WHERE person_id IS NULL AND lower(email) = ANY(%(e)s)',
               dict(e=emails))
    tx.execute('DELETE FROM address_session WHERE normalized_email = %(ne)s', dict(ne=ne))
    return covers


def purge(tx, now: Optional[datetime] = None) -> int:
    """The daily sweep (service/cron/leadretention): rows a day past their
    code and their session go, address and all."""
    now = _now(now)
    return tx.execute(
        """DELETE FROM address_session
            WHERE code_expires_at < %(cut)s
              AND (session_expires_at IS NULL OR session_expires_at < %(cut)s)""",
        dict(cut=now - KEEP_AFTER)).rowcount
