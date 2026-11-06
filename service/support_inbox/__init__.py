"""A copy of every message sent to support@ahavah.app (TEC-2115,
docs/plans/2026-11-05-support-messages-in-admin.md, and for how the mail
gets in, docs/plans/2026-11-05-support-inbox-via-forwarding.md).

support@ahavah.app is an alias delivered into the owner's main mailbox, so
the server holds no Google credential: a key for that mailbox would read all
of it. Instead a Gmail filter forwards mail addressed to support@ahavah.app
to a receiving address on the Techbase Resend account
(AHAVAH_SUPPORT_INBOUND_ADDRESS), and the supportinbox cron calls `tick`
every 5 minutes. A pass lists the received emails through Resend's API,
fetches each one whose To or Cc holds the support address or the inbound
address and that is not stored yet, and stores it in `support_message`.
Nothing is sent, and nothing in Resend or Gmail is changed.

Switched off by default. `tick` does nothing at all, and prints nothing,
while AHAVAH_SUPPORT_INBOX_ENABLED is off. With it on but no inbound
address, or no Resend key, it prints one line per process and checks
nothing. The key is AHAVAH_SUPPORT_RESEND_KEY, falling back to the Resend
key the API sends mail with (DUO_SMTP_PASS, when it is a Resend key).
Listing received mail needs a full-access key: a sending-only key answers
401 or 403, which the inbox status records and the admin shows.

How a pass reads the list (Resend keeps received mail 30 days, and does not
say which way the list is ordered, so the pass works either way):

  1. It reads pages of up to 100 from the top, each page after the last
     id of the one before, until the list ends. When the list comes newest
     first (seen from the received times), it stops early at a page whose
     every email is older than `synced_through`, less SYNC_SLACK: the
     newest received time of the last read that finished. A read that
     fails part way does not move `synced_through`, so the next pass reads
     as far again and nothing older is lost.
  2. At most MAX_PAGES_PER_PASS pages a pass. A read the limit cuts short
     keeps the id it reached (`backfill_token`) and the newest time it saw
     (`walk_newest`), carries on from there next pass, and says so in the
     log. Should Resend no longer know that id, the read starts again from
     the top in the same pass. `backfill_done` is true once a read has
     finished with nothing left over.
  3. Storing is idempotent on the Resend email id, so an email read twice
     is stored once, and one already stored is never fetched again.
  4. Resend allows 10 requests a second for the whole Techbase team, so
     the client spaces its calls (service/support_inbox/resend.py). A 429
     stops the pass where it is and keeps the place, as the page limit
     does; it is recorded in the inbox status as 'ResendError 429', and
     what the pass copied before it stands.

Mail received more than IMPORT_OPEN_DAYS (14) days before the first pass
is stored as handled, by 'Imported': the switch going on does not fill the
open list and the owner's alert with old mail.

A message that cannot be read (Resend answers 404 for it, or it cannot be
parsed or stored) goes on the retry list (support_inbox_state.retry_ids:
its id, attempts, when it first failed and when it arrived) and is tried
again at the start of each pass. synced_through does not move past it
while it waits. After RETRY_MAX_ATTEMPTS (10) attempts or RETRY_FOR (24
hours) it is given up, and its Resend id, never its content, is recorded
in the inbox status (last_error); it stays on the list, marked given up,
until Resend no longer holds it, so the walk does not take it up again.
Any other Resend error, or the database going away, fails the pass, which
reads from the same place next time.

Skipped, never stored: mail sent by the support address itself, automatic
replies (Auto-Submitted, X-Autoreply, X-Autorespond, Precedence:
auto_reply, and the mailer daemon), and anything older than the 1 year the
copies are kept. Gmail's forwarding confirmation
(forwarding-noreply@google.com) is never taken for an automatic reply: it
carries the code that switches the forwarding on. A message skipped is not
fetched again by the same process. Header text is stored without control
characters.

The member is the one account whose normalised email (normalize_email, as
person.normalized_email holds it) matches the sender's. Two or none: no
member.

"Reply in Gmail" opens a search of the owner's mailbox
(AHAVAH_SUPPORT_GMAIL_USER) for the original Message-ID.

PRIVACY: support messages are member content. Nothing here logs a body, a
subject or an address, only counts, an error's class name and HTTP status.
A failed pass prints one line, and only when the error differs from the
last one recorded, so a broken key does not fill the log.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from html import unescape
from html.parser import HTMLParser
from typing import Callable, Iterable, Optional, Protocol
from urllib.parse import quote

DEFAULT_MAILBOX = 'support@ahavah.app'
DEFAULT_GMAIL_USER = 'admin@techbaseltd.com'

BODY_MAX = 20_000
RETENTION_DAYS = 365

# Resend's list: up to 100 a page; at most this many pages a pass.
PAGE_LIMIT = 100
MAX_PAGES_PER_PASS = 20
# A newest-first read stops at a page all older than the last finished read
# by at least this much, so an email Resend lists a little late is still
# read.
SYNC_SLACK = timedelta(minutes=15)
# Resend statuses that mean it does not know a continuation cursor.
_CURSOR_REFUSED = frozenset({400, 404, 422})

# An email Resend lists but that cannot be read (404, or it cannot be parsed
# or stored) is tried again on later passes, and given up after this many
# attempts or this long since the first, whichever comes first. Until then
# synced_through does not move past it.
RETRY_MAX_ATTEMPTS = 10
RETRY_FOR = timedelta(hours=24)
# A given-up id stays on the list, marked, so the walk does not take it up
# again, until Resend (30 days) no longer holds the email.
GIVEN_UP_KEPT = timedelta(days=31)

# Mail older than this, counted back from the first pass, is imported as
# handled by IMPORTED_BY.
IMPORT_OPEN_DAYS = 14
IMPORTED_BY = 'Imported'
# The skipped ids recorded in last_error, at most.
FAILED_IDS_LISTED = 10

_AUTOMATIC_SENDERS = frozenset({'mailer-daemon', 'postmaster'})
# Automatic, but stored: Gmail's forwarding confirmation carries the code
# that switches the forwarding on.
_NEVER_AUTOMATIC = frozenset({'forwarding-noreply@google.com'})


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def enabled() -> bool:
    from service.campaigns.switches import enabled as switch_on
    return switch_on('support_inbox')


def mailbox() -> str:
    raw = os.environ.get('AHAVAH_SUPPORT_MAILBOX', '').strip().lower()
    return raw or DEFAULT_MAILBOX


def inbound_address() -> str:
    """The Resend receiving address the Gmail filter forwards to; empty
    until it is set up."""
    return os.environ.get('AHAVAH_SUPPORT_INBOUND_ADDRESS', '').strip().lower()


def resend_key() -> str:
    """AHAVAH_SUPPORT_RESEND_KEY, else the Resend key mail is sent with."""
    key = os.environ.get('AHAVAH_SUPPORT_RESEND_KEY', '').strip()
    if key:
        return key
    sending = os.environ.get('DUO_SMTP_PASS', '').strip()
    return sending if sending.startswith('re_') else ''


def gmail_user() -> str:
    return os.environ.get('AHAVAH_SUPPORT_GMAIL_USER', '').strip() or DEFAULT_GMAIL_USER


def gmail_url(*, rfc_message_id: Optional[str], thread_id: Optional[str]) -> Optional[str]:
    """For "Reply in Gmail": a search of the owner's mailbox for the
    original Message-ID; for a row the old Gmail reader copied, its thread
    as the support mailbox; otherwise None."""
    mid = (rfc_message_id or '').strip().strip('<>').strip()
    if mid:
        return (f'https://mail.google.com/mail/?authuser={gmail_user()}'
                f'#search/rfc822msgid%3A{quote(mid, safe="")}')
    if thread_id:
        return f'https://mail.google.com/mail/?authuser={mailbox()}#all/{thread_id}'
    return None


# ---------------------------------------------------------------------------
# the Resend client the pass uses (service/support_inbox/resend.py is the
# real one; tests pass a fake)
# ---------------------------------------------------------------------------

class ResendError(Exception):
    def __init__(self, status: int):
        super().__init__(f'HTTP {status}')
        self.status = status


class ResendClient(Protocol):
    def list_received(self, *, limit: int, after: Optional[str] = None) -> dict: ...

    def get_received(self, email_id: str) -> dict: ...


# ---------------------------------------------------------------------------
# reading one message
# ---------------------------------------------------------------------------

@dataclass
class Parsed:
    email_id: str
    rfc_message_id: Optional[str]
    from_address: str
    from_name: Optional[str]
    subject: str
    body_text: str
    received_at: datetime
    headers: dict


def _decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 -- a malformed header keeps its raw text
        return value


class _HtmlText(HTMLParser):
    _BLOCK = frozenset({'p', 'div', 'tr', 'li', 'ul', 'ol', 'table', 'blockquote', 'pre',
                        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'header',
                        'footer'})
    _HIDDEN = frozenset({'script', 'style', 'head', 'title'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self._hidden += 1
        elif tag == 'br':
            self.out.append('\n')
        elif tag in self._BLOCK:
            self.out.append('\n')

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.out.append('\n')

    def handle_endtag(self, tag):
        if tag in self._HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in self._BLOCK:
            self.out.append('\n')

    def handle_data(self, data):
        if not self._hidden:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _HtmlText()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 -- broken markup: fall back to stripping tags
        return unescape(re.sub(r'<[^>]+>', ' ', html))
    return ''.join(p.out)


def clean_text(text: str) -> str:
    """Line endings to \\n, no NUL (Postgres refuses it), spaces in a line
    collapsed, at most one blank line in a row, capped at BODY_MAX."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    lines = [re.sub(r'[ \t ]+', ' ', line).strip() for line in text.split('\n')]
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    return text[:BODY_MAX]


def body_text(email: dict) -> str:
    """The plain text; failing that the HTML as plain text; failing that
    nothing. Attachments are never read. Control characters but tab and
    newline are dropped."""
    text = email.get('text')
    if isinstance(text, str) and text.strip():
        return clean_text(_CONTROLS.sub('', text))
    html = email.get('html')
    if isinstance(html, str) and html.strip():
        return clean_text(_CONTROLS.sub('', html_to_text(html)))
    return ''


_OFFSET_HOURS_ONLY = re.compile(r'([+-]\d{2})$')


def parse_time(value) -> datetime:
    """Resend's created_at ('2026-11-05 10:42:17.123+00', or ISO 8601), in
    UTC. A time without a zone is taken as UTC. ValueError when unreadable."""
    s = str(value or '').strip()
    if s.endswith(('Z', 'z')):
        s = s[:-1] + '+00:00'
    s = _OFFSET_HOURS_ONLY.sub(r'\1:00', s)
    at = datetime.fromisoformat(s)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)


def _try_time(value) -> Optional[datetime]:
    try:
        return parse_time(value)
    except (TypeError, ValueError):
        return None


def _headers(email: dict) -> dict:
    """Header names in lower case, the first value of each."""
    raw = email.get('headers') or {}
    pairs: Iterable = raw.items() if isinstance(raw, dict) else (
        (h.get('name'), h.get('value')) for h in raw if isinstance(h, dict))
    out: dict = {}
    for name, value in pairs:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ''
        out.setdefault(str(name or '').lower(), '' if value is None else str(value))
    return out


def _addresses(*fields) -> set[str]:
    values: list[str] = []
    for field in fields:
        if isinstance(field, str):
            values.append(field)
        elif isinstance(field, (list, tuple)):
            values.extend(str(v) for v in field if v)
    return {addr.strip().lower() for _, addr in getaddresses(values) if addr.strip()}


def addressed_to(item: dict, targets: frozenset) -> bool:
    """True when the email's To or Cc holds one of `targets`."""
    return bool(_addresses(item.get('to'), item.get('cc')) & targets)


# Control characters but tab and newline; header-derived text keeps none.
# Tab (\x09), newline (\x0a) and carriage return (\x0d) are kept: clean_text
# turns every line ending, CR-only included, into \n.
_CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_ALL_CONTROLS = re.compile(r'[\x00-\x1f\x7f]')


def _header_text(value: str) -> str:
    """Header-derived text as stored: no control characters, one line."""
    return clean_text(_ALL_CONTROLS.sub(' ', value))


def parse(email: dict) -> Parsed:
    headers = _headers(email)
    raw_from = str(email.get('from') or '')
    # Parsed before decoding, so a comma in an encoded display name cannot
    # split the address. The name comes from the From header, else from a
    # "Name <addr>" in Resend's own from field.
    name, header_address = parseaddr(headers.get('from', ''))
    from_name, from_address = parseaddr(raw_from)
    name = name or from_name
    name = _decode_header_value(name) if name else name
    address = from_address or header_address
    subject = email.get('subject')
    if subject is None:
        subject = headers.get('subject', '')
    rfc = _ALL_CONTROLS.sub('', str(email.get('message_id') or headers.get('message-id') or ''))
    rfc = rfc.strip().strip('<>').strip()
    return Parsed(
        email_id=str(email['id']),
        rfc_message_id=rfc[:998] or None,
        from_address=_ALL_CONTROLS.sub('', address).strip().lower()[:320],
        from_name=(_header_text(name)[:200] or None) if name else None,
        subject=_header_text(_decode_header_value(str(subject)))[:998],
        body_text=body_text(email),
        received_at=parse_time(email.get('created_at')),
        headers=headers,
    )


def skip_reason(p: Parsed, box: str, now: datetime) -> Optional[str]:
    """Why a message is not stored, or None to store it."""
    if not p.from_address or '@' not in p.from_address:
        return 'no_sender'
    if p.from_address == box:
        return 'own'
    if p.received_at < now - timedelta(days=RETENTION_DAYS):
        return 'too_old'
    if p.from_address in _NEVER_AUTOMATIC:
        return None
    if p.from_address.split('@', 1)[0] in _AUTOMATIC_SENDERS:
        return 'automatic'
    auto = p.headers.get('auto-submitted', '').strip().lower()
    if auto and auto != 'no':
        return 'automatic'
    if 'x-autoreply' in p.headers or 'x-autorespond' in p.headers:
        return 'automatic'
    if p.headers.get('precedence', '').strip().lower() == 'auto_reply':
        return 'automatic'
    return None


# ---------------------------------------------------------------------------
# storing
# ---------------------------------------------------------------------------

_Q_PERSON_BY_NORMALISED_EMAIL = """
    SELECT id FROM person WHERE normalized_email = %(ne)s LIMIT 2
"""

_Q_INSERT = """
    INSERT INTO support_message (
        resend_email_id, rfc_message_id, from_address, from_name, subject,
        body_text, received_at, person_id, status, handled_by, handled_at)
    VALUES (
        %(rid)s, %(rfc)s, %(from_address)s, %(from_name)s, %(subject)s,
        %(body)s, %(received_at)s, %(person_id)s, %(status)s, %(handled_by)s,
        CASE WHEN %(status)s = 'open' THEN NULL ELSE NOW() END)
    ON CONFLICT (resend_email_id) DO NOTHING
    RETURNING id
"""

_Q_KNOWN = """
    SELECT resend_email_id FROM support_message WHERE resend_email_id = ANY(%(ids)s)
"""


def member_id(tx, address: str) -> Optional[int]:
    from antiabuse.antispam.signupemail import normalize_email
    ne = normalize_email(address)
    if not ne:
        return None
    rows = tx.execute(_Q_PERSON_BY_NORMALISED_EMAIL, dict(ne=ne)).fetchall()
    return int(rows[0]['id']) if len(rows) == 1 else None


def store(tx, p: Parsed, *, first_pass_at: Optional[datetime] = None) -> bool:
    """True when the message is new. Mail received more than
    IMPORT_OPEN_DAYS before the first pass is stored as handled by
    IMPORTED_BY."""
    imported = (first_pass_at is not None
                and p.received_at < first_pass_at - timedelta(days=IMPORT_OPEN_DAYS))
    row = tx.execute(_Q_INSERT, dict(
        rid=p.email_id, rfc=p.rfc_message_id, from_address=p.from_address,
        from_name=p.from_name, subject=p.subject, body=p.body_text,
        received_at=p.received_at, person_id=member_id(tx, p.from_address),
        status='handled' if imported else 'open',
        handled_by=IMPORTED_BY if imported else None,
    )).fetchone()
    return row is not None


def _known(ids: list[str]) -> set[str]:
    from database import api_tx
    if not ids:
        return set()
    with api_tx('read committed') as tx:
        return {r['resend_email_id'] for r in tx.execute(_Q_KNOWN, dict(ids=ids)).fetchall()}


# Ids this process skipped on purpose (automatic replies, own mail): not
# fetched again until it restarts. Bounded, so a long-lived cron cannot grow
# it without end. Mail that could not be read goes to the retry list
# instead (support_inbox_state.retry_ids).
_seen: set[str] = set()
_SEEN_MAX = 50_000


def _remember(email_id: str) -> None:
    if len(_seen) >= _SEEN_MAX:
        _seen.clear()
    _seen.add(email_id)


# ---------------------------------------------------------------------------
# where the read has got to
# ---------------------------------------------------------------------------

_Q_STATE = """
    INSERT INTO support_inbox_state (mailbox) VALUES (%(m)s)
    ON CONFLICT (mailbox) DO UPDATE SET mailbox = EXCLUDED.mailbox
    RETURNING backfill_done, backfill_token, synced_through, walk_newest, retry_ids, last_error,
              first_pass_at
"""

_Q_SAVE_READ = """
    UPDATE support_inbox_state
       SET backfill_done = %(done)s, backfill_token = %(token)s,
           synced_through = %(synced)s, walk_newest = %(walk_newest)s,
           retry_ids = %(retry)s::jsonb
     WHERE mailbox = %(m)s
"""

_Q_SAVE_RETRIES = """
    UPDATE support_inbox_state SET retry_ids = %(retry)s::jsonb WHERE mailbox = %(m)s
"""

_Q_CHECKED_OK = """
    UPDATE support_inbox_state
       SET last_checked_at = NOW(), last_ok_at = NOW(),
           -- A note of skipped messages stays until a later skip replaces
           -- it, so the admin sees it after the next clean pass; an error
           -- from a failed pass clears once a pass succeeds.
           last_error = COALESCE(%(e)s, CASE WHEN last_error LIKE %(note)s THEN last_error END)
     WHERE mailbox = %(m)s
"""
SKIPPED_NOTE = 'could not be read and were skipped'

_Q_FIRST_PASS = """
    UPDATE support_inbox_state SET first_pass_at = COALESCE(first_pass_at, %(at)s)
     WHERE mailbox = %(m)s
    RETURNING first_pass_at
"""

_Q_CHECKED_FAILED = """
    INSERT INTO support_inbox_state (mailbox, last_checked_at, last_error)
    VALUES (%(m)s, NOW(), %(e)s)
    ON CONFLICT (mailbox) DO UPDATE SET last_checked_at = NOW(), last_error = EXCLUDED.last_error
"""


def _state(box: str) -> dict:
    from database import api_tx
    with api_tx() as tx:
        return dict(tx.execute(_Q_STATE, dict(m=box)).fetchone())


def _save_read(box: str, *, done: bool, token: Optional[str], synced: Optional[datetime],
               walk_newest: Optional[datetime], retry: dict) -> None:
    from database import api_tx
    with api_tx() as tx:
        tx.execute(_Q_SAVE_READ, dict(m=box, done=done, token=token, synced=synced,
                                      walk_newest=walk_newest, retry=json.dumps(retry)))


def _save_retries(box: str, retry: dict) -> None:
    from database import api_tx
    with api_tx() as tx:
        tx.execute(_Q_SAVE_RETRIES, dict(m=box, retry=json.dumps(retry)))


# ---------------------------------------------------------------------------
# one pass
# ---------------------------------------------------------------------------

class _RateLimited(Exception):
    """Resend answered 429: the pass stops and keeps its place."""


def _read_one(client: ResendClient, rid: str, box: str, now: datetime,
              first_pass_at: Optional[datetime]) -> str:
    """Fetch, parse and store one email: 'stored', 'already', 'skipped' or
    'failed' (Resend's 404 for it, or any error parsing or storing it).
    A 429 raises _RateLimited; any other Resend error, and the database
    connection failing, raise and fail the pass."""
    import psycopg
    from database import api_tx
    try:
        email = client.get_received(rid)
    except ResendError as e:
        if e.status == 429:
            raise _RateLimited() from None
        if e.status != 404:
            raise
        return 'failed'
    try:
        p = parse(email)
        if skip_reason(p, box, now) is not None:
            _remember(rid)
            return 'skipped'
        with api_tx() as tx:
            new = store(tx, p, first_pass_at=first_pass_at)
    except (psycopg.OperationalError, psycopg.InterfaceError):
        raise
    except Exception:  # noqa: BLE001 -- this message only; recorded by id, never content
        return 'failed'
    return 'stored' if new else 'already'


def _give_up(entry: dict, now: datetime) -> bool:
    first = _try_time(entry.get('first'))
    return (int(entry.get('attempts') or 0) >= RETRY_MAX_ATTEMPTS
            or first is None or now - first >= RETRY_FOR)


def _retry(client: ResendClient, retry: dict, box: str, now: datetime, counts: dict,
           first_pass_at: Optional[datetime]) -> None:
    """Try each email on the retry list again. Read: off the list. Failed
    again: one more attempt counted, and after RETRY_MAX_ATTEMPTS
    attempts or RETRY_FOR since the first, given up and named in
    counts['failed_ids']."""
    known = _known(list(retry))
    for rid in list(retry):
        entry = retry[rid]
        if entry.get('given_up'):
            # Kept only so the list's walk does not take it up again, until
            # Resend no longer holds it.
            first = _try_time(entry.get('first'))
            if first is None or now - first > GIVEN_UP_KEPT:
                del retry[rid]
            continue
        if rid in known:
            del retry[rid]
            continue
        outcome = _read_one(client, rid, box, now, first_pass_at)
        if outcome == 'failed':
            entry['attempts'] = int(entry.get('attempts') or 0) + 1
            if _give_up(entry, now):
                entry['given_up'] = True
                counts['failed_ids'].append(rid)
            continue
        del retry[rid]
        counts[outcome] += 1


def _take(client: ResendClient, items: list[dict], box: str, now: datetime, counts: dict,
          retry: dict, first_pass_at: Optional[datetime]) -> None:
    """Fetch and store each email not already stored, skipped or waiting on
    the retry list. One that cannot be read goes on the retry list."""
    created = {}
    for item in items:
        created.setdefault(str(item['id']), item.get('created_at'))
    todo = [i for i in created if i not in _seen and i not in retry]
    known = _known(todo)
    for rid in todo:
        if rid in known:
            counts['already'] += 1
            continue
        outcome = _read_one(client, rid, box, now, first_pass_at)
        if outcome == 'failed':
            at = _try_time(created[rid])
            retry[rid] = dict(attempts=1, first=now.isoformat(), created=at.isoformat() if at else None)
            counts['retrying'] += 1
            continue
        counts[outcome] += 1


def _hold_back(synced: Optional[datetime], retry: dict) -> Optional[datetime]:
    """synced_through never passes an email still on the retry list."""
    waiting = [t for t in (_try_time(e.get('created')) for e in retry.values() if not e.get('given_up'))
               if t is not None]
    if synced is None or not waiting:
        return synced
    return min(synced, min(waiting) - timedelta(microseconds=1))


def poll(client: ResendClient, box: str, targets: frozenset, *,
         now: Optional[datetime] = None) -> dict:
    """One pass over Resend's received list. Returns counts only."""
    now = now or datetime.now(timezone.utc)
    counts: dict = dict(stored=0, skipped=0, already=0, pages=0, capped=0, restarted=0,
                        retrying=0, rate_limited=0, failed_ids=[])
    state = _state(box)
    first_pass_at = state['first_pass_at']
    if first_pass_at is None:
        from database import api_tx
        with api_tx() as tx:
            first_pass_at = tx.execute(_Q_FIRST_PASS, dict(m=box, at=now)).fetchone()['first_pass_at']

    retry: dict = dict(state['retry_ids'] or {})
    synced: Optional[datetime] = state['synced_through']
    token: Optional[str] = state['backfill_token']
    walk_newest: Optional[datetime] = state['walk_newest'] if token else None
    descending: Optional[bool] = None
    previous: Optional[datetime] = None
    page_cursor = token

    try:
        if retry:
            _retry(client, retry, box, now, counts, first_pass_at)
            _save_retries(box, retry)
        while True:
            if counts['pages'] >= MAX_PAGES_PER_PASS:
                counts['capped'] = 1
                _save_read(box, done=False, token=token, synced=synced, walk_newest=walk_newest,
                           retry=retry)
                break
            page_cursor = token
            try:
                page = client.list_received(limit=PAGE_LIMIT, after=token)
            except ResendError as e:
                if e.status == 429:
                    raise _RateLimited() from None
                if token and e.status in _CURSOR_REFUSED and not counts['restarted']:
                    counts['restarted'] = 1
                    token, walk_newest, descending, previous = None, None, None, None
                    continue
                raise
            counts['pages'] += 1
            items = [i for i in page.get('data') or [] if isinstance(i, dict) and i.get('id')]
            times = []
            for item in items:
                at = _try_time(item.get('created_at'))
                times.append(at)
                if at is None:
                    continue
                if descending is None and previous is not None and at != previous:
                    descending = at < previous
                previous = at
                walk_newest = at if walk_newest is None else max(walk_newest, at)
            _take(client, [i for i in items if addressed_to(i, targets)], box, now, counts, retry,
                  first_pass_at)
            if items:
                token = str(items[-1]['id'])
            caught_up = (descending is True and synced is not None and bool(items)
                         and all(at is not None and at < synced - SYNC_SLACK for at in times))
            if not items or not page.get('has_more') or caught_up:
                if walk_newest is not None:
                    synced = walk_newest if synced is None else max(synced, walk_newest)
                synced = _hold_back(synced, retry)
                _save_read(box, done=True, token=None, synced=synced, walk_newest=None, retry=retry)
                break
    except _RateLimited:
        # Keep the place: the page being read when Resend said 429 is read
        # again next pass (what it stored is not fetched again).
        counts['rate_limited'] = 1
        if page_cursor is None:
            _save_read(box, done=bool(state['backfill_done']), token=None, synced=state['synced_through'],
                       walk_newest=None, retry=retry)
        else:
            _save_read(box, done=False, token=page_cursor, synced=state['synced_through'],
                       walk_newest=walk_newest, retry=retry)
        counts['backfill_done'] = page_cursor is None and bool(state['backfill_done'])
        return counts

    counts['backfill_done'] = not counts['capped']
    return counts


# ---------------------------------------------------------------------------
# the cron's tick
# ---------------------------------------------------------------------------

_said_not_set_up = False


def _error_name(exc: BaseException) -> str:
    if isinstance(exc, ResendError):
        return f'ResendError {exc.status}'
    return type(exc).__name__


def _real_client(key: str) -> ResendClient:
    from service.support_inbox.resend import ResendReceiving
    return ResendReceiving(key)


def _record_failure(box: str, error: str) -> Optional[str]:
    """Record the failed pass; returns the error recorded before it."""
    from database import api_tx
    with api_tx() as tx:
        before = tx.execute('SELECT last_error FROM support_inbox_state WHERE mailbox = %(m)s',
                            dict(m=box)).fetchone()
        tx.execute(_Q_CHECKED_FAILED, dict(m=box, e=error[:200]))
    return before['last_error'] if before else None


def tick(make_client: Optional[Callable[[str], ResendClient]] = None,
         now: Optional[datetime] = None) -> dict:
    global _said_not_set_up
    if not enabled():
        return {'off': True}
    box, inbound, key = mailbox(), inbound_address(), resend_key()
    if not inbound or not key:
        if not _said_not_set_up:
            missing = ' and '.join(m for m, ok in (('no inbound address', inbound),
                                                    ('no Resend key', key)) if not ok)
            print(f'support_inbox: switched on, but there is {missing}; nothing checked', flush=True)
            _said_not_set_up = True
        return {'not_set_up': True}
    _said_not_set_up = False
    make_client = make_client or _real_client
    from database import api_tx
    try:
        counts = poll(make_client(key), box, frozenset({box, inbound}), now=now)
    except Exception as exc:  # noqa: BLE001 -- recorded by class name only, never content
        error = _error_name(exc)[:200]
        if _record_failure(box, error) != error:
            print(f'support_inbox: check failed ({error})', flush=True)
        return {'error': error}
    failed = counts['failed_ids']
    note = None
    if failed:
        listed = ', '.join(failed[:FAILED_IDS_LISTED])
        more = f' and {len(failed) - FAILED_IDS_LISTED} more' if len(failed) > FAILED_IDS_LISTED else ''
        note = f'{len(failed)} message(s) {SKIPPED_NOTE}: Resend ids {listed}{more}'
    if counts['rate_limited']:
        # Not a failed pass: what it copied stands and the place is kept.
        # Recorded, and printed when it changes, as a failure is.
        error = ('ResendError 429' + (f'; {note}' if note else ''))[:200]
        if _record_failure(box, error) != error:
            print(f'support_inbox: Resend rate limit ({error}); '
                  f"{counts['stored']} new message(s) copied, the rest next pass", flush=True)
        return counts
    with api_tx() as tx:
        tx.execute(_Q_CHECKED_OK, dict(m=box, e=note, note=f'%{SKIPPED_NOTE}%'))
    if counts['stored'] or counts['capped'] or counts['restarted'] or failed or counts['retrying']:
        print(f"support_inbox: {counts['stored']} new message(s) copied, "
              f"{counts['skipped']} skipped"
              + (f", {counts['retrying']} could not be read and will be tried again"
                 if counts['retrying'] else '')
              + (f', {len(failed)} given up after trying again' if failed else '')
              + (', the saved place in the list was gone so it was read again from the top'
                 if counts['restarted'] else '')
              + (f', page limit ({MAX_PAGES_PER_PASS}) reached so the rest is read next pass'
                 if counts['capped'] else ''),
              flush=True)
    return counts


# ---------------------------------------------------------------------------
# retention (the lead_retention cron, daily)
# ---------------------------------------------------------------------------

_Q_PURGE = """
    DELETE FROM support_message WHERE received_at < NOW() - make_interval(days => %(days)s)
"""


def purge_old(tx) -> int:
    return tx.execute(_Q_PURGE, dict(days=RETENTION_DAYS)).rowcount
