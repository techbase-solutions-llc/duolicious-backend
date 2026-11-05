"""A copy of every message sent to support@ahavah.app (TEC-2115,
docs/plans/2026-11-05-support-messages-in-admin.md).

The supportinbox cron calls `tick` every 5 minutes. It reads the support
mailbox through the Gmail API, read only, with a Google service account that
has domain-wide delegation for the one scope gmail.readonly, and stores each
new message in `support_message`. Nothing is sent, forwarded, labelled or
marked read in the mailbox.

Switched off by default. `tick` does nothing at all, and prints nothing,
while AHAVAH_SUPPORT_INBOX_ENABLED is off. With it on but no key file at
AHAVAH_SUPPORT_GMAIL_KEY_PATH, it prints one line per process and checks
nothing.

How a pass reads the mailbox:

  1. The first pass records the mailbox's current history id, then reads the
     whole mailbox a few pages per pass (the backfill), so mail from before
     the switch was turned on comes in too. The backfill's page token is
     kept in `support_inbox_state`, so a restart carries on where it was.
  2. Every pass after that asks Gmail for the messages added since the
     stored history id, and moves the history id on only once each of them
     has been stored or skipped. Gmail keeps history for about a week; a
     cursor older than that answers 404, and the pass starts the backfill
     again from the current history id. Storing is idempotent on the Gmail
     message id, so a message read twice is stored once.

Skipped, never stored: mail sent by the mailbox itself, drafts, chats, spam
and trash, automatic replies (Auto-Submitted, X-Autoreply, X-Autorespond,
Precedence: auto_reply, and the mailer daemon), and anything older than the
1 year the copies are kept.

The member is the one account whose normalised email (normalize_email, as
person.normalized_email holds it) matches the sender's. Two or none: no
member.

PRIVACY: support messages are member content. Nothing here logs a body, a
subject or an address, only counts and an error's class name. A failed pass
prints one line naming the error class, and only when it differs from the
last one recorded, so a broken key does not fill the log.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
from typing import Callable, Optional, Protocol

DEFAULT_MAILBOX = 'support@ahavah.app'
DEFAULT_KEY_PATH = '/run/ahavah-secrets/support-gmail.json'
SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'

BODY_MAX = 20_000
RETENTION_DAYS = 365
# Pages of the backfill read per pass, of up to 100 messages each.
BACKFILL_PAGES_PER_PASS = 3

# Mailbox searches the backfill runs: everything but what the mailbox sent
# and its drafts and chats. Gmail leaves spam and trash out of a search
# unless asked.
BACKFILL_QUERY = '-in:sent -in:drafts -in:chats'

_SKIP_LABELS = frozenset({'SENT', 'DRAFT', 'CHAT', 'SPAM', 'TRASH'})
_AUTOMATIC_SENDERS = frozenset({'mailer-daemon', 'postmaster'})


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def enabled() -> bool:
    from service.campaigns.switches import enabled as switch_on
    return switch_on('support_inbox')


def mailbox() -> str:
    raw = os.environ.get('AHAVAH_SUPPORT_MAILBOX', '').strip().lower()
    return raw or DEFAULT_MAILBOX


def key_path() -> str:
    return os.environ.get('AHAVAH_SUPPORT_GMAIL_KEY_PATH', '').strip() or DEFAULT_KEY_PATH


def gmail_url(thread_id: str, box: Optional[str] = None) -> str:
    """The thread in Gmail, opened as the support mailbox, for "Reply in
    Gmail"."""
    return f'https://mail.google.com/mail/?authuser={box or mailbox()}#all/{thread_id}'


# ---------------------------------------------------------------------------
# the Gmail client the pass uses (service/support_inbox/gmail.py is the real
# one; tests pass a fake)
# ---------------------------------------------------------------------------

class HistoryExpired(Exception):
    """The stored history id is older than Gmail keeps (about a week)."""


class GmailError(Exception):
    def __init__(self, status: int):
        super().__init__(f'HTTP {status}')
        self.status = status


class GmailClient(Protocol):
    def current_history_id(self) -> str: ...

    def list_message_ids(self, page_token: Optional[str]) -> tuple[list[str], Optional[str]]: ...

    def history(self, start_history_id: str,
                page_token: Optional[str]) -> tuple[list[dict], Optional[str], str]: ...

    def get_message(self, message_id: str) -> dict: ...


# ---------------------------------------------------------------------------
# reading one message
# ---------------------------------------------------------------------------

@dataclass
class Parsed:
    message_id: str
    thread_id: str
    labels: frozenset
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


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))


_CHARSET = re.compile(r'charset\s*=\s*"?([^";\s]+)', re.I)


def _part_text(part: dict) -> str:
    data = (part.get('body') or {}).get('data')
    if not data:
        return ''
    headers = {h['name'].lower(): h['value'] for h in part.get('headers') or []}
    m = _CHARSET.search(headers.get('content-type', ''))
    charset = m.group(1) if m else 'utf-8'
    raw = _b64url(data)
    try:
        return raw.decode(charset, errors='replace')
    except LookupError:
        return raw.decode('utf-8', errors='replace')


def _is_attachment(part: dict) -> bool:
    return bool(part.get('filename')) or bool((part.get('body') or {}).get('attachmentId'))


def _walk(part: dict):
    yield part
    for child in part.get('parts') or []:
        yield from _walk(child)


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


def body_text(payload: dict) -> str:
    """The message's first plain-text part; failing that its first HTML part
    as plain text; failing that nothing. Attachments are never read."""
    parts = [p for p in _walk(payload) if not _is_attachment(p)]
    for p in parts:
        if (p.get('mimeType') or '').lower() == 'text/plain':
            text = _part_text(p)
            if text.strip():
                return clean_text(text)
    for p in parts:
        if (p.get('mimeType') or '').lower() == 'text/html':
            text = _part_text(p)
            if text.strip():
                return clean_text(html_to_text(text))
    return ''


def parse(msg: dict) -> Parsed:
    payload = msg.get('payload') or {}
    headers: dict = {}
    for h in payload.get('headers') or []:
        headers.setdefault(str(h.get('name', '')).lower(), str(h.get('value', '')))
    # Parsed before decoding, so a comma in an encoded display name cannot
    # split the address.
    name, address = parseaddr(headers.get('from', ''))
    name = _decode_header_value(name) if name else name
    received = datetime.fromtimestamp(int(msg.get('internalDate') or 0) / 1000, tz=timezone.utc)
    subject = clean_text(_decode_header_value(headers.get('subject', '')))[:998]
    return Parsed(
        message_id=str(msg['id']),
        thread_id=str(msg.get('threadId') or msg['id']),
        labels=frozenset(msg.get('labelIds') or []),
        from_address=address.strip().lower()[:320],
        from_name=(clean_text(name)[:200] or None) if name else None,
        subject=subject,
        body_text=body_text(payload),
        received_at=received,
        headers=headers,
    )


def skip_reason(p: Parsed, box: str, now: datetime) -> Optional[str]:
    """Why a message is not stored, or None to store it."""
    if p.labels & _SKIP_LABELS:
        return 'label'
    if not p.from_address or '@' not in p.from_address:
        return 'no_sender'
    if p.from_address == box:
        return 'own'
    if p.from_address.split('@', 1)[0] in _AUTOMATIC_SENDERS:
        return 'automatic'
    auto = p.headers.get('auto-submitted', '').strip().lower()
    if auto and auto != 'no':
        return 'automatic'
    if 'x-autoreply' in p.headers or 'x-autorespond' in p.headers:
        return 'automatic'
    if p.headers.get('precedence', '').strip().lower() == 'auto_reply':
        return 'automatic'
    if p.received_at < now - timedelta(days=RETENTION_DAYS):
        return 'too_old'
    return None


# ---------------------------------------------------------------------------
# storing
# ---------------------------------------------------------------------------

_Q_PERSON_BY_NORMALISED_EMAIL = """
    SELECT id FROM person WHERE normalized_email = %(ne)s LIMIT 2
"""

_Q_INSERT = """
    INSERT INTO support_message (
        gmail_message_id, gmail_thread_id, from_address, from_name, subject,
        body_text, received_at, person_id)
    VALUES (
        %(mid)s, %(tid)s, %(from_address)s, %(from_name)s, %(subject)s,
        %(body)s, %(received_at)s, %(person_id)s)
    ON CONFLICT (gmail_message_id) DO NOTHING
    RETURNING id
"""

_Q_KNOWN = """
    SELECT gmail_message_id FROM support_message WHERE gmail_message_id = ANY(%(ids)s)
"""


def member_id(tx, address: str) -> Optional[int]:
    from antiabuse.antispam.signupemail import normalize_email
    ne = normalize_email(address)
    if not ne:
        return None
    rows = tx.execute(_Q_PERSON_BY_NORMALISED_EMAIL, dict(ne=ne)).fetchall()
    return int(rows[0]['id']) if len(rows) == 1 else None


def store(tx, p: Parsed) -> bool:
    """True when the message is new."""
    row = tx.execute(_Q_INSERT, dict(
        mid=p.message_id, tid=p.thread_id, from_address=p.from_address,
        from_name=p.from_name, subject=p.subject, body=p.body_text,
        received_at=p.received_at, person_id=member_id(tx, p.from_address),
    )).fetchone()
    return row is not None


def _known(ids: list[str]) -> set[str]:
    from database import api_tx
    if not ids:
        return set()
    with api_tx('read committed') as tx:
        return {r['gmail_message_id'] for r in tx.execute(_Q_KNOWN, dict(ids=ids)).fetchall()}


# ---------------------------------------------------------------------------
# the cursor
# ---------------------------------------------------------------------------

_Q_STATE = """
    INSERT INTO support_inbox_state (mailbox) VALUES (%(m)s)
    ON CONFLICT (mailbox) DO UPDATE SET mailbox = EXCLUDED.mailbox
    RETURNING history_id, backfill_done, backfill_token, last_error
"""

_Q_SAVE_CURSOR = """
    UPDATE support_inbox_state
       SET history_id = %(history_id)s, backfill_done = %(backfill_done)s,
           backfill_token = %(backfill_token)s
     WHERE mailbox = %(m)s
"""

_Q_CHECKED_OK = """
    UPDATE support_inbox_state
       SET last_checked_at = NOW(), last_ok_at = NOW(), last_error = NULL
     WHERE mailbox = %(m)s
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


def _save_cursor(box: str, *, history_id: Optional[str], backfill_done: bool,
                 backfill_token: Optional[str]) -> None:
    from database import api_tx
    with api_tx() as tx:
        tx.execute(_Q_SAVE_CURSOR, dict(m=box, history_id=history_id, backfill_done=backfill_done,
                                        backfill_token=backfill_token))


# ---------------------------------------------------------------------------
# one pass
# ---------------------------------------------------------------------------

def _take(client: GmailClient, ids: list[str], box: str, now: datetime, counts: dict,
          labels: Optional[dict] = None) -> None:
    """Fetch and store each id not already stored. `labels` (from the
    history) lets mail the mailbox sent be skipped without fetching it."""
    from database import api_tx
    labels = labels or {}
    todo = []
    for mid in dict.fromkeys(ids):
        if frozenset(labels.get(mid) or ()) & _SKIP_LABELS:
            counts['skipped'] += 1
        else:
            todo.append(mid)
    known = _known(todo)
    for mid in todo:
        if mid in known:
            counts['already'] += 1
            continue
        p = parse(client.get_message(mid))
        if skip_reason(p, box, now) is not None:
            counts['skipped'] += 1
            continue
        with api_tx() as tx:
            if store(tx, p):
                counts['stored'] += 1
            else:
                counts['already'] += 1


def poll(client: GmailClient, box: str, *, now: Optional[datetime] = None) -> dict:
    """One pass over the mailbox. Returns counts only."""
    now = now or datetime.now(timezone.utc)
    counts = dict(stored=0, skipped=0, already=0, backfill_pages=0, restarted=0)
    state = _state(box)
    history_id = state['history_id']
    backfill_done = bool(state['backfill_done'])
    backfill_token = state['backfill_token']

    if history_id is None:
        history_id = client.current_history_id()
        backfill_done, backfill_token = False, None
        _save_cursor(box, history_id=history_id, backfill_done=False, backfill_token=None)
    else:
        added: list[dict] = []
        token: Optional[str] = None
        latest = history_id
        try:
            while True:
                page, token, latest = client.history(history_id, token)
                added.extend(page)
                if not token:
                    break
        except HistoryExpired:
            counts['restarted'] = 1
            history_id = client.current_history_id()
            backfill_done, backfill_token = False, None
            _save_cursor(box, history_id=history_id, backfill_done=False, backfill_token=None)
        else:
            labels = {str(m['id']): m.get('labelIds') or [] for m in added}
            _take(client, [str(m['id']) for m in added], box, now, counts, labels)
            history_id = latest or history_id
            _save_cursor(box, history_id=history_id, backfill_done=backfill_done,
                         backfill_token=backfill_token)

    while not backfill_done and counts['backfill_pages'] < BACKFILL_PAGES_PER_PASS:
        ids, next_token = client.list_message_ids(backfill_token)
        _take(client, ids, box, now, counts)
        counts['backfill_pages'] += 1
        backfill_token = next_token
        backfill_done = next_token is None
        _save_cursor(box, history_id=history_id, backfill_done=backfill_done,
                     backfill_token=backfill_token)

    counts['backfill_done'] = backfill_done
    return counts


# ---------------------------------------------------------------------------
# the cron's tick
# ---------------------------------------------------------------------------

_said_no_key = False
_client_cache: dict = {}


def _error_name(exc: BaseException) -> str:
    if isinstance(exc, GmailError):
        return f'GmailError {exc.status}'
    return type(exc).__name__


def _real_client(path: str, box: str) -> GmailClient:
    """One client per key file and mailbox, kept between passes so its
    access token is reused until it lapses."""
    from service.support_inbox.gmail import GmailApi
    key = (path, box, os.path.getmtime(path))
    client = _client_cache.get(key)
    if client is None:
        _client_cache.clear()
        client = _client_cache[key] = GmailApi(path, box)
    return client


def _record_failure(box: str, error: str) -> Optional[str]:
    """Record the failed pass; returns the error recorded before it."""
    from database import api_tx
    with api_tx() as tx:
        before = tx.execute('SELECT last_error FROM support_inbox_state WHERE mailbox = %(m)s',
                            dict(m=box)).fetchone()
        tx.execute(_Q_CHECKED_FAILED, dict(m=box, e=error[:200]))
    return before['last_error'] if before else None


def tick(make_client: Optional[Callable[[str, str], GmailClient]] = None,
         now: Optional[datetime] = None) -> dict:
    global _said_no_key
    if not enabled():
        return {'off': True}
    path, box = key_path(), mailbox()
    if make_client is None:
        if not os.path.isfile(path):
            if not _said_no_key:
                print('support_inbox: switched on, but there is no key file; nothing checked', flush=True)
                _said_no_key = True
            return {'no_key': True}
        make_client = _real_client
    _said_no_key = False
    from database import api_tx
    try:
        counts = poll(make_client(path, box), box, now=now)
    except Exception as exc:  # noqa: BLE001 -- recorded by class name only, never content
        error = _error_name(exc)
        if _record_failure(box, error) != error:
            print(f'support_inbox: check failed ({error})', flush=True)
        return {'error': error}
    with api_tx() as tx:
        tx.execute(_Q_CHECKED_OK, dict(m=box))
    if counts['stored'] or counts['restarted']:
        print(f"support_inbox: {counts['stored']} new message(s) copied, "
              f"{counts['skipped']} skipped"
              + (', history too old so the full read started again' if counts['restarted'] else ''),
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
