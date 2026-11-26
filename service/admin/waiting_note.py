"""Write to them (TEC-2210, plan ahavah-admin/docs/plans/2026-11-26-admin-dead-buttons.md,
part 1).

The owner writes a short note to one member on the Waiting on a reply list
and it goes by email on the member note shell (emails/member_note.py), with
a copy to the admin inbox. One press sends one email; nothing here runs by
itself.

The order of a send:

1. The note is checked (clean_note): plain text, 1 to 600 characters, no
   link and no angle bracket.
2. In one transaction, under an advisory lock on the member, the member is
   looked up and every refusal checked, then a waiting_note row is written
   and committed. That row is the claim: a second press, even one that
   lands while the mail server is still answering the first, finds it and
   is refused as too_soon.
3. The email is sent. If it fails, or the mailer finds the address
   suppressed, the row is deleted, so nothing is recorded and the owner can
   try again.
4. After a send the audit row is written (`waiting_note`, the member's uuid
   and the note's length, never the text).
"""
from __future__ import annotations

import html
import re
from typing import Optional

import duotypes as t
from database import api_tx
from emails import member_note
from emails.base import suppressed_sql_pattern
from service.admin import record_audit
from service.admin.jsonrow import iso
from service.admin.queries import community
from service.admin.queries.members import counted_member_sql
from service.campaigns import schedule, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded

NOTE_MAX = 600
PREHEADER_MAX = 90
WINDOW_DAYS = community.NOTE_WINDOW_DAYS
SUBJECT = 'A note from Ahavah'
BUTTON_LABEL = 'Open Ahavah'
# The page where a member sees who has liked them, as the likes waiting
# email links (emails/likes_waiting.py).
BUTTON_URL = f'{WEB_BASE_URL}/matches'
SEND_KIND = 'waiting_note'
AUDIT_ACTION = 'waiting_note'

# The advisory lock's first key; the second is the person id.
_LOCK_KEY = "hashtext('waiting_note')"


class BadNote(ValueError):
    """The note cannot be sent as written. The message says why."""


class NotFound(Exception):
    """No person has this uuid."""


class Refused(Exception):
    """A 409: `code` is one of not_waiting, too_soon, rest_day,
    unsubscribed and not_reachable."""

    def __init__(self, code: str, can_note_at: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.can_note_at = can_note_at

    def body(self) -> dict:
        out = dict(error=self.code)
        if self.can_note_at is not None:
            out['can_note_at'] = self.can_note_at
        return out


class SendFailed(Exception):
    """The mail server or the send guard refused the member's copy."""


def clean_note(raw: Optional[str]) -> str:
    """The note as it will be stored and sent: line endings made \\n and
    trimmed. Raises BadNote."""
    text = (raw or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        raise BadNote('The note is empty.')
    if len(text) > NOTE_MAX:
        raise BadNote(f'The note is {len(text)} characters. The most a note can be is {NOTE_MAX}.')
    low = text.lower()
    if 'http' in low or 'www.' in low:
        raise BadNote('The note holds a link. Take it out: the button in the email opens Ahavah.')
    if '<' in text or '>' in text:
        raise BadNote('The note holds an angle bracket. Take it out and send it as plain text.')
    return text


def paragraphs(note: str) -> list[str]:
    """Blank lines split paragraphs; a single line break stays a line
    break. Everything is HTML-escaped, since member_note inserts each
    paragraph as HTML."""
    out = []
    for block in re.split(r'\n\s*\n', note):
        lines = [line.strip() for line in block.strip().split('\n')]
        if any(lines):
            out.append('<br/>'.join(html.escape(line) for line in lines))
    return out


def preheader(note: str) -> str:
    """The first 90 characters of the note on one line, escaped."""
    return html.escape(' '.join(note.split())[:PREHEADER_MAX].rstrip())


_Q_PERSON = f"""
    SELECT p.id, p.uuid::text AS uuid, p.email,
           ({counted_member_sql('p')} AND p.deletion_requested_at IS NULL) AS reachable,
           ({unsubscribed_predicate_sql('campaigns', 'p.id')}
            OR {suppressed_predicate_sql('p.email')})                      AS unsubscribed
      FROM person p
     WHERE p.uuid = %(uuid)s::uuid
"""

_Q_LOCK = f"SELECT pg_advisory_xact_lock({_LOCK_KEY}, %(pid)s)"

_Q_LATEST = f"""
    SELECT max(sent_at) + INTERVAL '{WINDOW_DAYS} days' AS can_note_at
      FROM waiting_note
     WHERE person_id = %(pid)s
    HAVING max(sent_at) > NOW() - INTERVAL '{WINDOW_DAYS} days'
"""

_Q_CLAIM = f"""
    INSERT INTO waiting_note (person_id, sent_by, note)
    VALUES (%(pid)s, %(by)s, %(note)s)
    RETURNING id, sent_at, sent_at + INTERVAL '{WINDOW_DAYS} days' AS can_note_at
"""

_Q_RELEASE = "DELETE FROM waiting_note WHERE id = %(id)s"


def _claim(s: t.SessionInfo, person_uuid: str, note: str) -> dict:
    """Check every refusal and write the claim row, in one transaction.
    Returns the person's id and email and the claim. Raises NotFound or
    Refused."""
    params = dict(uuid=person_uuid, ex=_excluded(), sup=suppressed_sql_pattern())
    with api_tx('read committed') as tx:
        person = tx.execute(_Q_PERSON, params).fetchone()
        if person is None:
            raise NotFound()
        if schedule.campaign_rest_now() or schedule.campaign_beyond_known_now():
            raise Refused('rest_day')
        if not person['reachable']:
            raise Refused('not_reachable')
        if person['unsubscribed']:
            raise Refused('unsubscribed')
        pid = person['id']
        # Two presses wait here in turn; the second then reads the first's
        # committed row below.
        tx.execute(_Q_LOCK, dict(pid=pid))
        if not tx.execute(community.Q_IS_WAITING, dict(pid=pid, ex=params['ex'])).fetchone()['waiting']:
            raise Refused('not_waiting')
        latest = tx.execute(_Q_LATEST, dict(pid=pid)).fetchone()
        if latest is not None:
            raise Refused('too_soon', can_note_at=iso(latest['can_note_at']))
        claim = tx.execute(_Q_CLAIM, dict(pid=pid, by=s.email, note=note)).fetchone()
    return dict(uuid=person['uuid'], email=person['email'], claim=claim)


def _release(claim_id: int) -> None:
    with api_tx() as tx:
        tx.execute(_Q_RELEASE, dict(id=claim_id))


def send_note(s: t.SessionInfo, person_uuid: str, note: str) -> dict:
    """Send `note` (already through clean_note) to the member. Returns the
    200 body. Raises NotFound, Refused or SendFailed; after either of the
    last two from the send itself nothing is recorded."""
    got = _claim(s, person_uuid, note)
    claim = got['claim']
    try:
        delivered = member_note.send_member_note(
            to_addr=got['email'],
            subject=SUBJECT,
            preheader=preheader(note),
            paragraphs=paragraphs(note),
            button_label=BUTTON_LABEL,
            button_url=BUTTON_URL,
            cc_admin=True,
            kind=SEND_KIND,
            raise_on_failure=True,
        )
    except Exception as e:
        _release(claim['id'])
        raise SendFailed(str(e)) from e
    if not delivered:
        # The mailer's own suppression list caught the address.
        _release(claim['id'])
        raise Refused('unsubscribed')
    with api_tx() as tx:
        record_audit(tx, s, AUDIT_ACTION, target_uuid=got['uuid'],
                     metadata=dict(member=got['uuid'], note_length=len(note)))
    return dict(sent=True, note_sent_at=iso(claim['sent_at']), can_note_at=iso(claim['can_note_at']))
