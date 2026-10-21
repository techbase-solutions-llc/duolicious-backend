"""Matchmaker, release 1 (TEC-1845): alerts, introductions and read-only
mentors.

docs/superpowers/specs/2026-10-13-matchmaker-design.md and
docs/superpowers/plans/2026-10-21-matchmaker-release-1.md.

  regions        alpha-2 country code to continent (continents.json)
  criteria       what an alert looks for, its words and the fit query
  mail           every matchmaker email and push, queueing and previews
  alerts         a member's alert; a visitor's, confirmed by link
  notices        the daily member notice and the weekly visitor notice
  recommend      "Introduce a single to Ahavah", once per address
  introductions  "Suggest two people": the picker, the answers, the match
  mentors        the single's side: invite, remove, share a conversation
  mentor_view    the mentor's side: sign in, matches, notes, conversations
  moderation     notes held for Moderation > Text
  admin          the Growth counts and a member's connections, counts only
  retention      the sweep, deleting with the account, crediting a single

Dark until launch: while matchmaker_live is off (AHAVAH_MATCHMAKER_LIVE_
ENABLED, service/campaigns/switches.py) every matchmaker route but
/matchmaker/status answers 404 and nothing is queued or sent, whichever way
its own switch is set. Each surface (members' alerts, visitors' alerts,
introductions, mentors), each email and each push has its own switch,
which counts only once matchmaker_live is on. The proofs (scripts/
send_matchmaker_proofs.py) and the admin routes work either way.

Lines marked NEW LINE are not in the export; they wait for /copy-pass and
the owner (plan item 21).
"""
from __future__ import annotations

import hashlib
import hmac
import unicodedata
from typing import Literal, Optional

from service.campaigns.switches import enabled

# Each matchmaker email's outbox campaign and its switch. The outbox drain
# reads it again at send time (service/campaigns/outbox.py), so a switch
# turned off after a row was queued stops it.
CAMPAIGN_SWITCHES: dict[str, str] = {
    'mm_alert': 'matchmaker_alert_email',
    'mm_visitor_confirm': 'matchmaker_visitor_confirm_email',
    'mm_visitor_alert': 'matchmaker_visitor_alert_email',
    'mm_recommend': 'matchmaker_recommend_email',
    'mm_intro': 'matchmaker_intro_email',
    'mm_mentor_invite': 'matchmaker_mentor_invite_email',
}

Surface = Literal['matchmaker_alerts', 'matchmaker_visitor_alerts',
                  'matchmaker_introductions', 'matchmaker_mentors']


class MatchmakerError(Exception):
    """A refusal the routes answer as {error: reason, **extra} with this
    status."""

    def __init__(self, reason: str, status: int = 400, extra: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.extra = dict(extra or {})


def live() -> bool:
    """The matchmaker is launched: the routes answer."""
    return enabled('matchmaker_live')


def surface_on(name: Surface) -> bool:
    """A surface opened after launch, which counts only once live."""
    return live() and enabled(name)


def switch_on(name: str) -> bool:
    """A switch (an email's or a push's, usually) which counts only once
    live."""
    return live() and enabled(name)


def address_key(normalized_email: str) -> str:
    """A keyed hash of an address (HMAC-SHA256 with the unsubscribe
    secret), so a recommended single's address can be erased while we still
    know never to email it twice. A plain hash of an address is easy to
    reverse by guessing; this one needs the secret."""
    from service.unsubscribe import _secret
    return hmac.new(_secret(), normalized_email.strip().lower().encode(),
                    hashlib.sha256).hexdigest()


def first_name(name: Optional[str]) -> str:
    """The first word of a name, or 'Someone' when there is none."""
    words = (name or '').split()
    return words[0] if words else 'Someone'  # NEW LINE


def clean_first_name(value: object, max_len: int = 40) -> Optional[str]:
    """A first name as typed: control characters out, runs of space to one,
    trimmed. None when empty; MatchmakerError('bad_first_name') when it is
    not text or longer than max_len."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise MatchmakerError('bad_first_name', 400)
    text = ''.join(ch if ch.isspace() or unicodedata.category(ch) not in ('Cc', 'Cf', 'Cs', 'Co')
                   else '' for ch in value)
    text = ' '.join(text.split())
    if not text:
        return None
    if len(text) > max_len:
        raise MatchmakerError('bad_first_name', 400)
    return text


def is_uuid(value: object) -> bool:
    """A well-formed uuid, checked before it reaches SQL: a bad cast would
    abort the caller's transaction."""
    import uuid as _uuid
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        _uuid.UUID(value)
    except ValueError:
        return False
    return True
