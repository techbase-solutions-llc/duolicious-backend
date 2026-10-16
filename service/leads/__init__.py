"""Leads: people who gave Ahavah an email before joining (TEC-1845).

docs/superpowers/plans/2026-10-16-growth-foundations.md. One table
(migration 0066) shared by the couple tools, gathering RSVPs and visitor
alerts, so the dashboard counts them one way and the privacy page
describes one thing.

  - One row per address and source. The address is matched on its
    normalised form (antiabuse normalize_email), so Ann.Lee+x@gmail.com
    and annlee@gmail.com are one lead.
  - A member is not a lead: record_lead writes nothing for an address that
    has an account and answers None.
  - Marketing consent is a ticked box, stored with the key of the wording
    shown. A later visit with the box unticked never withdraws it; the
    unsubscribe link does (scope 'news', service/unsubscribe), on every row
    of the address. A fresh tick after that is only pending: the form needs
    no proof of the address, so it counts once a confirm link issued after
    it is tapped (confirm_by_token).
  - A confirm link's token is stored only as its sha256. It works for
    CONFIRM_TTL and may be tapped more than once.
  - Rows go RETENTION_DAYS after last_seen_at, or a day after the confirm
    link lapsed if never confirmed (service/cron/leadretention), or with
    the member's account (service/hard_delete.py).

Every function takes the caller's transaction and never opens one, unless
its docstring says otherwise.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from antiabuse.antispam.signupemail import normalize_email
from service.leads.sources import is_lead_source

CONFIRM_TTL = timedelta(days=7)
RETENTION_DAYS = 365
CONFIRMED_VIA = ('otp', 'link')
_TOKEN_MIN, _TOKEN_MAX = 16, 64


def clean_email(email: object) -> Optional[tuple[str, str]]:
    """(lower-cased address, normalised address), or None for anything that
    is not plausibly an address."""
    if not isinstance(email, str):
        return None
    address = email.strip().lower()
    if address.count('@') != 1 or len(address) > 254 or any(c.isspace() for c in address):
        return None
    local, _, domain = address.partition('@')
    if not local or '.' not in domain:
        return None
    return address, normalize_email(address)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """An unguessable URL-safe token of 32 characters, and the hash to store."""
    token = secrets.token_urlsafe(24)
    return token, token_hash(token)


_Q_IS_MEMBER = """
    SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1
"""

_Q_UPSERT = """
    INSERT INTO lead (email, normalized_email, source, marketing_consent,
                      consent_wording, consented_at)
    VALUES (%(e)s, %(ne)s, %(src)s, %(mc)s, %(cw)s,
            CASE WHEN %(mc)s::boolean THEN NOW() END)
    ON CONFLICT (normalized_email, source) DO UPDATE SET
        email             = EXCLUDED.email,
        last_seen_at      = NOW(),
        marketing_consent = lead.marketing_consent
                            OR (EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL),
        consent_wording   = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL
                                 THEN EXCLUDED.consent_wording ELSE lead.consent_wording END,
        consented_at      = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL
                                 THEN NOW() ELSE lead.consented_at END,
        -- An unsubscribed address stays unsubscribed: whoever ticked the box
        -- has not proved the address is theirs. The tick waits here until a
        -- confirm link issued after it is tapped (_Q_CONFIRM_BY_TOKEN).
        consent_pending_wording = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NOT NULL
                                       THEN EXCLUDED.consent_wording ELSE lead.consent_pending_wording END,
        consent_pending_at      = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NOT NULL
                                       THEN NOW() ELSE lead.consent_pending_at END
    RETURNING id
"""


def record_lead(tx, *, email: str, source: str, marketing_consent: bool = False,
                consent_wording: Optional[str] = None) -> Optional[int]:
    """Record (or refresh) the lead for this address and source and return
    its id, or None when the address belongs to a member. Raises ValueError
    'bad_source', 'bad_email' or 'consent_wording_required'."""
    if not is_lead_source(source):
        raise ValueError('bad_source')
    consent = marketing_consent is True
    if consent and not (isinstance(consent_wording, str) and consent_wording.strip()):
        raise ValueError('consent_wording_required')
    cleaned = clean_email(email)
    if cleaned is None:
        raise ValueError('bad_email')
    address, normalised = cleaned
    if tx.execute(_Q_IS_MEMBER, dict(ne=normalised)).fetchone():
        return None
    row = tx.execute(_Q_UPSERT, dict(e=address, ne=normalised, src=source, mc=consent,
                                     cw=consent_wording.strip() if consent else None)).fetchone()
    return row['id']


def confirm_lead(tx, lead_id: int, via: str) -> None:
    """The address is proved: by a sign-in code ('otp') or a link ('link').
    The first proof is the one kept."""
    if via not in CONFIRMED_VIA:
        raise ValueError('bad_via')
    tx.execute(
        """UPDATE lead SET confirmed_at = COALESCE(confirmed_at, NOW()),
                           confirmed_via = COALESCE(confirmed_via, %(via)s),
                           last_seen_at = NOW()
            WHERE id = %(id)s""",
        dict(id=lead_id, via=via))


def issue_confirm_token(tx, lead_id: int) -> str:
    """A new confirm token for the link in a confirmation email. Replaces
    any earlier one; only its hash is stored."""
    token, hashed = new_token()
    tx.execute(
        """UPDATE lead SET confirm_token_hash = %(h)s,
                           confirm_token_expires_at = NOW() + %(ttl)s
            WHERE id = %(id)s""",
        dict(h=hashed, ttl=CONFIRM_TTL, id=lead_id))
    return token


# A token was issued at confirm_token_expires_at - CONFIRM_TTL. Only one
# issued at or after a pending tick (record_lead on an unsubscribed address)
# turns that tick into consent and lifts the unsubscribe.
_Q_CONFIRM_BY_TOKEN = """
    UPDATE lead SET
        confirmed_at            = COALESCE(lead.confirmed_at, NOW()),
        confirmed_via           = COALESCE(lead.confirmed_via, 'link'),
        last_seen_at            = NOW(),
        marketing_consent       = lead.marketing_consent OR t.resume,
        consent_wording         = CASE WHEN t.resume THEN lead.consent_pending_wording
                                       ELSE lead.consent_wording END,
        consented_at            = CASE WHEN t.resume THEN NOW() ELSE lead.consented_at END,
        unsubscribed_at         = CASE WHEN t.resume THEN NULL ELSE lead.unsubscribed_at END,
        consent_pending_wording = CASE WHEN t.resume THEN NULL ELSE lead.consent_pending_wording END,
        consent_pending_at      = CASE WHEN t.resume THEN NULL ELSE lead.consent_pending_at END
      FROM (SELECT id,
                   (consent_pending_at IS NOT NULL
                    AND confirm_token_expires_at - %(ttl)s >= consent_pending_at) AS resume
              FROM lead
             WHERE confirm_token_hash = %(h)s AND confirm_token_expires_at > NOW()) AS t
     WHERE lead.id = t.id
    RETURNING lead.id
"""


def confirm_by_token(tx, token: object) -> Optional[int]:
    """The lead a confirm link names, now confirmed, or None for a token
    that is malformed, lapsed or was never issued. Tapping it again while it
    lasts answers the same lead. A token issued after a pending tick also
    turns that tick into consent and lifts the unsubscribe."""
    if not isinstance(token, str) or not _TOKEN_MIN <= len(token) <= _TOKEN_MAX:
        return None
    row = tx.execute(_Q_CONFIRM_BY_TOKEN, dict(h=token_hash(token), ttl=CONFIRM_TTL)).fetchone()
    return row['id'] if row else None


def touch_lead(tx, lead_id: int) -> None:
    """A visit: restarts the 12 month clock."""
    tx.execute('UPDATE lead SET last_seen_at = NOW() WHERE id = %(id)s', dict(id=lead_id))


def lead_unsubscribed(tx, lead_id: int) -> bool:
    """True when this lead has left the news mail, or no longer exists
    (fails towards not mailing)."""
    row = tx.execute('SELECT unsubscribed_at IS NOT NULL AS u FROM lead WHERE id = %(id)s',
                     dict(id=lead_id)).fetchone()
    return True if row is None else bool(row['u'])
