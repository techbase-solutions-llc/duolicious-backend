"""Support messages in the admin (TEC-2115,
docs/plans/2026-11-05-support-messages-in-admin.md and
docs/plans/2026-11-05-support-inbox-via-forwarding.md).

Rules locked in here:
  1. Off by default: with the switch off a pass does nothing and prints
     nothing; on with no inbound address or no Resend key it reads nothing
     and says so once.
  2. A new message is stored once; a second pass fetches nothing again.
     Only mail whose To or Cc holds the support address or the inbound
     address is fetched.
  3. The Resend list is read correctly whichever way it is ordered; a read
     that fails part way loses nothing; the page limit carries on in the
     next pass.
  4. Mail the support address sent and automatic replies are skipped, and
     not fetched again.
  5. The member is matched by normalised email, and only when exactly one
     account matches.
  6. HTML-only mail is stored as plain text; every body is capped at 20,000
     characters.
  7. Nothing printed names a sender, a subject or a body: counts and an
     error's class name and HTTP status only.
  8. The admin routes are admin only; marking is audited, once, and a second
     mark answers 409. "Reply in Gmail" searches the owner's mailbox for the
     message id.
  9. The owner's daily alert lists open messages older than 24 hours by
     number and age only, once a day.
 10. Copies are deleted a year after they arrived.
 11. One message that cannot be read is skipped, by id, and the pass moves
     on; other Resend errors still fail the pass.
 12. Mail more than 14 days older than the first pass comes in handled, by
     'Imported'; the alert counts age from the later of arrival and copy.
 13. The send guard's tick does not read support messages while the switch
     is off, and a failed read cannot break the rest of the tick.

No test calls Resend: every pass gets a fake client.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from uuid import uuid4

import pytest

import smtp as smtp_mod
from database import api_tx
from service import sendguard, support_inbox
from service.support_inbox import admin as support_admin

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = [ROOT / 'migrations' / '0093_support_messages.sql',
              ROOT / 'migrations' / '0094_support_messages_resend.sql']
SECRET_SUBJECT = 'Please unlock my account SUBJECT-SECRET'
SECRET_BODY = 'My account is locked. BODY-SECRET'


def _resend_time(at: datetime) -> str:
    """Resend's created_at, e.g. 2026-11-05 10:42:17.123+00."""
    return at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + '+00'


def rmail(rid: str, *, to=('support@ahavah.app',), cc=(), frm: str = 'Rivka Levi <rivka@ahavah-test.invalid>',
          subject: str = SECRET_SUBJECT, text: str | None = SECRET_BODY, html: str | None = None,
          extra_headers: dict | None = None, received: datetime | None = None,
          message_id: str | None = None) -> dict:
    """A received email as GET /emails/receiving/{id} answers it."""
    received = received or datetime.now(timezone.utc) - timedelta(minutes=3)
    message_id = message_id or f'<{rid}@mail.ahavah-test.invalid>'
    headers = {'From': frm, 'To': ', '.join(to), 'Subject': subject, 'Message-ID': message_id}
    headers.update(extra_headers or {})
    return {
        'object': 'email', 'id': rid, 'to': list(to), 'cc': list(cc), 'bcc': [], 'reply_to': [],
        'from': parseaddr(frm)[1], 'created_at': _resend_time(received), 'subject': subject,
        'html': html, 'text': text, 'headers': headers, 'received_for': list(to),
        'message_id': message_id, 'authentication': {},
        'raw': {'download_url': 'https://example.invalid/raw', 'expires_at': _resend_time(received)},
        'attachments': [{'id': 'att-1', 'filename': 'scan.pdf', 'content_type': 'application/pdf',
                         'size': 1000}],
    }


_SUMMARY_KEYS = ('id', 'to', 'from', 'created_at', 'subject', 'bcc', 'cc', 'reply_to', 'message_id',
                 'attachments')


class FakeResend:
    """The two calls a pass makes, over an in-memory received list. Newest
    first unless `ascending`; pages of `page_size` (2) so paging is
    exercised. `after` is the id of the last item of the page before, as
    Resend's cursor works."""

    def __init__(self, emails: list[dict], *, ascending: bool = False, page_size: int = 2):
        self.emails = {e['id']: e for e in emails}
        self.ascending = ascending
        self.page_size = page_size
        self.fetched: list[str] = []
        self.lists: list[str | None] = []
        self.fail: Exception | None = None
        self.fail_ids: dict[str, Exception] = {}
        self.fail_after: dict[str, Exception] = {}

    def _ordered(self) -> list[dict]:
        out = sorted(self.emails.values(), key=lambda e: (e['created_at'], e['id']))
        return out if self.ascending else out[::-1]

    def list_received(self, *, limit: int, after: str | None = None) -> dict:
        assert 1 <= limit <= 100
        self.lists.append(after)
        if self.fail:
            raise self.fail
        if after in self.fail_after:
            raise self.fail_after.pop(after)  # once: the cursor it had saved
        ordered = self._ordered()
        start = 0
        if after is not None:
            ids = [e['id'] for e in ordered]
            if after not in ids:
                raise support_inbox.ResendError(422)
            start = ids.index(after) + 1
        size = min(limit, self.page_size)
        page = ordered[start:start + size]
        return {'object': 'list', 'has_more': start + size < len(ordered),
                'data': [{k: e[k] for k in _SUMMARY_KEYS} for e in page]}

    def get_received(self, email_id: str) -> dict:
        self.fetched.append(email_id)
        if email_id in self.fail_ids:
            raise self.fail_ids[email_id]
        return self.emails[email_id]

    def deliver(self, email: dict) -> None:
        self.emails[email['id']] = email


@pytest.fixture
def inbox(monkeypatch):
    """The switch on, a support address, inbound address and key of this
    test's own, and every row it made deleted afterwards. `inbox.ids(n)`
    gives Resend ids no other run uses; `inbox.mail(id, ...)` an email to
    this test's support address."""
    tag = uuid4().hex[:10]
    box = f'support-{tag}@ahavah-test.invalid'
    inbound = f'fwd-{tag}@inbound.ahavah-test.invalid'
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_SUPPORT_MAILBOX', box)
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOUND_ADDRESS', inbound)
    monkeypatch.setenv('AHAVAH_SUPPORT_RESEND_KEY', 're_test_key')
    monkeypatch.setattr(support_inbox, '_said_not_set_up', False)
    monkeypatch.setattr(support_inbox, '_seen', set())
    keys: list[str] = []

    class _Inbox:
        mailbox = box
        inbound_address = inbound
        keys_used = keys

        @staticmethod
        def ids(n: int) -> list[str]:
            return [f'{tag}-{i}' for i in range(n)]

        @staticmethod
        def mail(rid: str, **kw) -> dict:
            kw.setdefault('to', (box,))
            return rmail(rid, **kw)

        @staticmethod
        def run(client, now=None) -> dict:
            return support_inbox.tick(make_client=lambda key: keys.append(key) or client, now=now)

    yield _Inbox
    with api_tx() as tx:
        tx.execute('DELETE FROM support_message WHERE resend_email_id LIKE %(p)s', dict(p=f'{tag}-%'))
        tx.execute('DELETE FROM support_inbox_state WHERE mailbox = %(m)s', dict(m=box))


def _rows(ids: list[str]) -> list[dict]:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM support_message WHERE resend_email_id = ANY(%(i)s) ORDER BY id',
                          dict(i=ids)).fetchall()


def _stored(ids: list[str]) -> set[str]:
    return {r['resend_email_id'] for r in _rows(ids)}


def _state(box: str) -> dict | None:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM support_inbox_state WHERE mailbox = %(m)s', dict(m=box)).fetchone()


# --- 1. off by default, and not set up ------------------------------------------------

def test_the_switch_is_off_unless_set(monkeypatch, capsys):
    monkeypatch.delenv('AHAVAH_SUPPORT_INBOX_ENABLED', raising=False)
    called = []
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'off': True}
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', 'yes please')
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'off': True}
    assert called == [] and capsys.readouterr().out == ''


@pytest.mark.parametrize('missing', ['address', 'key'])
def test_on_but_not_set_up_checks_nothing_and_says_so_once(inbox, monkeypatch, capsys, missing):
    if missing == 'address':
        monkeypatch.delenv('AHAVAH_SUPPORT_INBOUND_ADDRESS')
    else:
        monkeypatch.delenv('AHAVAH_SUPPORT_RESEND_KEY')
        monkeypatch.setenv('DUO_SMTP_PASS', 'unused-in-dev-env')  # not a Resend key
    called = []
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'not_set_up': True}
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'not_set_up': True}
    out = capsys.readouterr().out
    assert out.count('support_inbox:') == 1 and 'nothing checked' in out
    assert ('no inbound address' in out) == (missing == 'address')
    assert ('no Resend key' in out) == (missing == 'key')
    assert called == [] and _state(inbox.mailbox) is None


def test_the_key_falls_back_to_the_resend_key_mail_is_sent_with(inbox, monkeypatch):
    monkeypatch.delenv('AHAVAH_SUPPORT_RESEND_KEY')
    monkeypatch.setenv('DUO_SMTP_PASS', 're_sending_key')
    assert support_inbox.resend_key() == 're_sending_key'
    inbox.run(FakeResend([]))
    assert inbox.keys_used == ['re_sending_key']
    monkeypatch.setenv('AHAVAH_SUPPORT_RESEND_KEY', ' re_full_access ')
    assert support_inbox.resend_key() == 're_full_access'


def test_the_defaults(monkeypatch):
    for name in ('AHAVAH_SUPPORT_MAILBOX', 'AHAVAH_SUPPORT_INBOUND_ADDRESS', 'AHAVAH_SUPPORT_GMAIL_USER'):
        monkeypatch.delenv(name, raising=False)
    assert support_inbox.mailbox() == 'support@ahavah.app'
    assert support_inbox.inbound_address() == ''
    assert support_inbox.gmail_user() == 'admin@techbaseltd.com'
    text = (ROOT / 'docker-compose.production.yml').read_text()
    assert text.count('AHAVAH_SUPPORT_INBOX_ENABLED: ${AHAVAH_SUPPORT_INBOX_ENABLED:-0}') == 2
    assert text.count('AHAVAH_SUPPORT_INBOUND_ADDRESS: ${AHAVAH_SUPPORT_INBOUND_ADDRESS:-}') == 2
    assert text.count('AHAVAH_SUPPORT_GMAIL_USER: ${AHAVAH_SUPPORT_GMAIL_USER:-admin@techbaseltd.com}') == 2
    assert text.count('AHAVAH_SUPPORT_RESEND_KEY: ${AHAVAH_SUPPORT_RESEND_KEY:-}') == 1  # the cron only
    assert 'DUO_CRON_SUPPORT_INBOX_POLL_SECONDS: ${DUO_CRON_SUPPORT_INBOX_POLL_SECONDS:-300}' in text
    # No Google key anywhere: no key path, no secrets mount, no google-auth.
    assert 'GMAIL_KEY' not in text and 'ahavah-secrets' not in text
    assert 'google-auth' not in (ROOT / 'requirements.txt').read_text()
    assert not (ROOT / 'service' / 'support_inbox' / 'gmail.py').exists()


# --- 2. stored once, and only support mail -----------------------------------------------

def test_the_first_pass_reads_the_whole_list_and_stores_each_message_once(inbox, capsys):
    ids = inbox.ids(5)
    now = datetime.now(timezone.utc)
    client = FakeResend([inbox.mail(i, received=now - timedelta(minutes=10 * n)) for n, i in enumerate(ids)])
    out = inbox.run(client)
    assert out['stored'] == 5 and out['backfill_done'] is True
    rows = {r['resend_email_id']: r for r in _rows(ids)}
    assert set(rows) == set(ids)
    r = rows[ids[1]]
    assert r['rfc_message_id'] == f'{ids[1]}@mail.ahavah-test.invalid'
    assert r['gmail_message_id'] is None and r['gmail_thread_id'] is None
    assert abs(r['received_at'] - (now - timedelta(minutes=10))) < timedelta(milliseconds=2)
    st = _state(inbox.mailbox)
    assert st['backfill_done'] and st['last_ok_at'] and st['last_error'] is None
    assert abs(st['synced_through'] - now) < timedelta(milliseconds=2)

    fetched = len(client.fetched)
    out = inbox.run(client)
    assert out['stored'] == 0 and len(client.fetched) == fetched  # nothing fetched again
    assert len(_rows(ids)) == 5
    assert '5 new message(s) copied' in capsys.readouterr().out


def test_only_mail_to_the_support_or_inbound_address_is_fetched(inbox):
    to_support, cc_support, upper, inbound, named, other, bcc_only = inbox.ids(7)
    client = FakeResend([
        inbox.mail(to_support),
        inbox.mail(cc_support, to=('someone@ahavah-test.invalid',), cc=(inbox.mailbox,)),
        inbox.mail(upper, to=(inbox.mailbox.upper(),)),
        inbox.mail(inbound, to=(inbox.inbound_address,)),  # Gmail's forwarding confirmation
        inbox.mail(named, to=(f'Ahavah Support <{inbox.mailbox}>',)),
        inbox.mail(other, to=('invoices@ahavah-test.invalid',)),
        inbox.mail(bcc_only, to=('someone@ahavah-test.invalid',)),
    ])
    out = inbox.run(client)
    assert out['stored'] == 5
    assert _stored(inbox.ids(7)) == {to_support, cc_support, upper, inbound, named}
    assert other not in client.fetched and bcc_only not in client.fetched


# --- 3. the list's order, failures part way, and the page limit ------------------------------

def _spaced(inbox, ids, *, start: datetime, minutes: int = 10, **kw) -> list[dict]:
    """Emails `minutes` apart, the first the oldest."""
    return [inbox.mail(i, received=start + timedelta(minutes=minutes * n), **kw) for n, i in enumerate(ids)]


def test_newest_first_a_later_pass_stops_at_mail_it_has_already_read(inbox):
    ids = inbox.ids(9)
    start = datetime.now(timezone.utc) - timedelta(days=2)
    client = FakeResend(_spaced(inbox, ids[:8], start=start, minutes=60))
    assert inbox.run(client)['stored'] == 8
    assert len(client.lists) == 4  # 8 emails, pages of 2

    client.lists.clear()
    client.deliver(inbox.mail(ids[8]))
    out = inbox.run(client)
    assert out['stored'] == 1 and _stored([ids[8]]) == {ids[8]}
    # The new one and the page after it, which is all older than the last read.
    assert len(client.lists) == 2


def test_oldest_first_new_mail_at_the_end_is_found(inbox):
    ids = inbox.ids(6)
    start = datetime.now(timezone.utc) - timedelta(days=2)
    client = FakeResend(_spaced(inbox, ids[:5], start=start), ascending=True)
    assert inbox.run(client)['stored'] == 5
    client.deliver(inbox.mail(ids[5]))
    assert inbox.run(client)['stored'] == 1
    assert _stored(ids) == set(ids)
    assert inbox.run(client)['stored'] == 0


def test_a_read_that_fails_part_way_loses_nothing(inbox):
    ids = inbox.ids(6)
    start = datetime.now(timezone.utc) - timedelta(days=2)
    client = FakeResend(_spaced(inbox, ids, start=start))
    oldest = ids[0]  # on the last page, newest first
    client.fail_ids[oldest] = support_inbox.ResendError(500)
    assert inbox.run(client) == {'error': 'ResendError 500'}
    assert _stored(ids) == set(ids[1:])
    assert _state(inbox.mailbox)['synced_through'] is None  # the read did not finish
    del client.fail_ids[oldest]
    out = inbox.run(client)
    assert out['stored'] == 1 and _stored(ids) == set(ids)


@pytest.mark.parametrize('ascending', [False, True])
def test_the_page_limit_carries_on_in_the_next_pass(inbox, monkeypatch, capsys, ascending):
    monkeypatch.setattr(support_inbox, 'MAX_PAGES_PER_PASS', 2)
    ids = inbox.ids(9)
    start = datetime.now(timezone.utc) - timedelta(days=2)
    client = FakeResend(_spaced(inbox, ids, start=start), ascending=ascending)
    out = inbox.run(client)
    assert out['stored'] == 4 and out['capped'] == 1 and out['backfill_done'] is False
    st = _state(inbox.mailbox)
    assert st['backfill_token'] and not st['backfill_done']
    assert 'page limit (2) reached' in capsys.readouterr().out
    out = inbox.run(client)
    assert out['stored'] == 4 and out['capped'] == 1
    out = inbox.run(client)
    assert out['stored'] == 1 and out['backfill_done'] is True
    assert _stored(ids) == set(ids)
    st = _state(inbox.mailbox)
    assert st['backfill_token'] is None and st['backfill_done']
    newest = start + timedelta(minutes=80)
    assert abs(st['synced_through'] - newest) < timedelta(milliseconds=2)


def test_a_cursor_resend_no_longer_has_starts_the_read_again(inbox, monkeypatch, capsys):
    monkeypatch.setattr(support_inbox, 'MAX_PAGES_PER_PASS', 1)
    ids = inbox.ids(4)
    start = datetime.now(timezone.utc) - timedelta(days=2)
    client = FakeResend(_spaced(inbox, ids, start=start))
    inbox.run(client)
    token = _state(inbox.mailbox)['backfill_token']
    client.fail_after[token] = support_inbox.ResendError(422)  # e.g. expired after 30 days
    monkeypatch.setattr(support_inbox, 'MAX_PAGES_PER_PASS', 10)
    out = inbox.run(client)
    assert out['restarted'] == 1 and out['backfill_done'] is True
    assert _stored(ids) == set(ids)
    assert 'read again from the top' in capsys.readouterr().out


# --- 4. skipped ---------------------------------------------------------------------------

def test_own_mail_and_automatic_replies_are_skipped_and_not_fetched_again(inbox):
    keep, own_from, auto, autoreply, prec, daemon, kept_no = inbox.ids(7)
    client = FakeResend([
        inbox.mail(keep),
        inbox.mail(own_from, frm=f'Ahavah Support <{inbox.mailbox.upper()}>'),
        inbox.mail(auto, extra_headers={'Auto-Submitted': 'auto-replied'}),
        inbox.mail(autoreply, extra_headers={'X-Autoreply': 'yes'}),
        inbox.mail(prec, extra_headers={'Precedence': 'auto_reply'}),
        inbox.mail(daemon, frm='Mail Delivery Subsystem <mailer-daemon@googlemail.com>'),
        inbox.mail(kept_no, extra_headers={'auto-submitted': 'no'}),
    ])
    out = inbox.run(client)
    assert out['stored'] == 2 and out['skipped'] == 5
    assert _stored(inbox.ids(7)) == {keep, kept_no}
    fetched = len(client.fetched)
    out = inbox.run(client)
    assert out['stored'] == 0 and out['skipped'] == 0 and len(client.fetched) == fetched


# --- 5. the member ----------------------------------------------------------------------------

def test_the_member_is_matched_by_normalised_email(inbox, make_person):
    tag = uuid4().hex[:8]
    member = make_person(name='Rivka', email=f'rivka{tag}@gmail.com')
    matched, stranger = inbox.ids(2)
    inbox.run(FakeResend([
        inbox.mail(matched, frm=f'Rivka <Rivka.{tag}+support@GoogleMail.com>'),
        inbox.mail(stranger, frm='Nobody <nobody-at-all@ahavah-test.invalid>'),
    ]))
    rows = {r['resend_email_id']: r for r in _rows([matched, stranger])}
    assert rows[matched]['person_id'] == member['id']
    assert rows[matched]['from_address'] == f'rivka.{tag}+support@googlemail.com'
    assert rows[matched]['from_name'] == 'Rivka'
    assert rows[stranger]['person_id'] is None


# --- 6. the text ------------------------------------------------------------------------------

def test_html_only_mail_is_stored_as_plain_text_and_bodies_are_capped(inbox):
    html_id, long_id = inbox.ids(2)
    html = ('<html><head><style>p{color:red}</style><title>t</title></head><body>'
            '<p>Shalom,</p><p>My account&nbsp;is <b>locked</b>.<br>Please help &amp; thanks</p>'
            '<script>alert(1)</script></body></html>')
    inbox.run(FakeResend([inbox.mail(html_id, text=None, html=html),
                          inbox.mail(long_id, text='x' * 30_000)]))
    rows = {r['resend_email_id']: r for r in _rows([html_id, long_id])}
    assert rows[html_id]['body_text'] == 'Shalom,\n\nMy account is locked.\nPlease help & thanks'
    assert len(rows[long_id]['body_text']) == 20_000


def test_the_display_name_comes_from_the_from_header_and_is_decoded():
    hebrew = 'Shalom עזרה'
    msg = rmail('x', frm='=?utf-8?q?Ren=C3=A9e?= <Renee@ahavah-test.invalid>', subject=hebrew,
                text='Café \x00ok', message_id=' <abc@mail.ahavah-test.invalid> ')
    msg['from'] = 'renee@ahavah-test.invalid'  # Resend gives the bare address
    p = support_inbox.parse(msg)
    assert p.subject == hebrew and p.from_name == 'Renée'
    assert p.from_address == 'renee@ahavah-test.invalid' and p.body_text == 'Café ok'
    assert p.rfc_message_id == 'abc@mail.ahavah-test.invalid'
    assert p.received_at.tzinfo is not None


@pytest.mark.parametrize('raw', ['2026-11-05 10:42:17.123+00', '2026-11-05T10:42:17.123Z',
                                 '2026-11-05T10:42:17.123+00:00', '2026-11-05 10:42:17.123'])
def test_resend_times_are_read_as_utc(raw):
    assert support_inbox.parse_time(raw) == datetime(2026, 11, 5, 10, 42, 17, 123000, tzinfo=timezone.utc)


# --- 7. nothing personal in the log ------------------------------------------------------------

def test_a_failed_pass_records_the_error_class_and_status_and_prints_it_once(inbox, capsys):
    [mid] = inbox.ids(1)
    client = FakeResend([inbox.mail(mid)])
    inbox.run(client)
    client.fail = support_inbox.ResendError(403)  # a sending-only key
    assert inbox.run(client) == {'error': 'ResendError 403'}
    assert inbox.run(client) == {'error': 'ResendError 403'}
    st = _state(inbox.mailbox)
    assert st['last_error'] == 'ResendError 403' and st['last_checked_at'] > st['last_ok_at']
    out = capsys.readouterr().out
    assert out.count('check failed (ResendError 403)') == 1
    client.fail = None
    inbox.run(client)
    assert _state(inbox.mailbox)['last_error'] is None


def test_nothing_printed_names_a_sender_a_subject_or_a_body(inbox, capsys):
    ids = inbox.ids(3)
    client = FakeResend([inbox.mail(i) for i in ids])
    inbox.run(client)
    client.fail = ValueError(f'{SECRET_SUBJECT} rivka@ahavah-test.invalid')
    inbox.run(client)
    out = capsys.readouterr().out
    assert out
    for secret in ('SUBJECT-SECRET', 'BODY-SECRET', 'rivka', '@', inbox.mailbox, 're_test_key'):
        assert secret not in out


# --- the real client, without the network ---------------------------------------------------------

class _Response:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kw):
        self.calls.append(dict(url=url, **kw))
        return self.responses.pop(0)


def test_the_resend_client_asks_for_received_mail_with_the_key(monkeypatch):
    from service.support_inbox import resend
    monkeypatch.setattr(resend, 'MIN_INTERVAL_SECONDS', 0)
    session = _Session(_Response(200, {'object': 'list', 'has_more': False, 'data': []}),
                       _Response(200, {'object': 'email', 'id': 'e/1'}),
                       _Response(401), _Response(403))
    client = resend.ResendReceiving('re_key', session=session)
    assert client.list_received(limit=100, after='abc') == {'object': 'list', 'has_more': False, 'data': []}
    assert client.get_received('e/1')['id'] == 'e/1'
    with pytest.raises(support_inbox.ResendError) as e:
        client.list_received(limit=100)
    assert e.value.status == 401
    with pytest.raises(support_inbox.ResendError) as e:
        client.get_received('x')
    assert e.value.status == 403
    first, second, third = session.calls[:3]
    assert first['url'] == 'https://api.resend.com/emails/receiving'
    assert first['params'] == {'limit': 100, 'after': 'abc'} and third['params'] == {'limit': 100}
    assert second['url'] == 'https://api.resend.com/emails/receiving/e%2F1'
    for call in session.calls:
        assert call['headers']['Authorization'] == 'Bearer re_key'
        assert call['headers']['User-Agent'].startswith('ahavah-backend/')
        assert call['timeout'] == 30


# --- 7. the admin routes --------------------------------------------------------------

LIST = '/admin/support/messages'
HANDLED = '/admin/support/messages/{}/handled'
NOT_FOR_US = '/admin/support/messages/{}/not-for-us'
REOPEN = '/admin/support/messages/{}/reopen'


@pytest.fixture
def support_rows():
    made: list[int] = []

    def _make(*, hours_old: int = 1, person_id=None, status='open', subject=SECRET_SUBJECT,
              body=SECRET_BODY, copied_hours_old: int | None = None, source: str = 'resend') -> int:
        """A copied message. `source`: 'resend' (a Resend id and the
        original Message-ID), 'gmail' (a row from the old Gmail reader) or
        'none' (neither id)."""
        # Copied when it arrived, unless the test says otherwise.
        copied = hours_old if copied_hours_old is None else copied_hours_old
        mid = f'route-{uuid4().hex}'
        ids = dict(resend=None, rfc=None, gmail=None, thread=None)
        if source == 'resend':
            ids.update(resend=mid, rfc=f'{mid}@mail.ahavah-test.invalid')
        elif source == 'gmail':
            ids.update(gmail=mid, thread=f'{mid}-t')
        with api_tx() as tx:
            rid = tx.execute(
                """INSERT INTO support_message (resend_email_id, rfc_message_id, gmail_message_id,
                                                gmail_thread_id, from_address, from_name,
                                                subject, body_text, received_at, person_id, status,
                                                created_at)
                   VALUES (%(resend)s, %(rfc)s, %(gmail)s, %(thread)s, 'sender@ahavah-test.invalid', 'Sender',
                           %(s)s, %(b)s, NOW() - make_interval(hours => %(h)s), %(p)s, %(st)s,
                           NOW() - make_interval(hours => %(c)s))
                   RETURNING id""",
                dict(ids, s=subject, b=body, h=hours_old, p=person_id, st=status, c=copied),
            ).fetchone()['id']
        made.append(rid)
        return rid

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM support_message WHERE id = ANY(%(i)s)', dict(i=made))


def _audits(mid: int) -> list[dict]:
    with api_tx('read committed') as tx:
        return tx.execute(
            "SELECT action, target_uuid, target_email, metadata FROM admin_audit_log "
            "WHERE action LIKE 'support_%%' AND metadata->>'support_message_id' = %(m)s ORDER BY id",
            dict(m=str(mid))).fetchall()


def test_admins_only(client, make_person, sign_in, support_rows):
    mid = support_rows()
    member = sign_in(make_person(name='NotAdmin'))
    assert client.get(LIST, headers=member).status_code == 403
    assert client.post(HANDLED.format(mid), headers=member).status_code == 403
    assert client.post(NOT_FOR_US.format(mid), headers=member).status_code == 403
    assert client.post(REOPEN.format(mid), headers=member).status_code == 403
    assert client.get(LIST).status_code in (400, 401, 403)  # no session


def test_the_list_carries_what_the_admin_needs(client, admin_headers, make_person, support_rows):
    member = make_person(name='Listed')
    with_member = support_rows(person_id=member['id'], hours_old=3)
    without = support_rows(hours_old=2, body='Short note\n\n  with   spaces')
    r = client.get(LIST, headers=admin_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {'messages', 'counts', 'page', 'page_size', 'has_more', 'inbox'}
    assert set(body['counts']) == {'open', 'handled', 'not_for_us'}
    assert set(body['inbox']) == {'enabled', 'mailbox', 'last_checked_at', 'last_ok_at', 'last_error',
                                  'backfill_done'}
    rows = {m['id']: m for m in body['messages']}
    assert with_member in rows and without in rows
    m = rows[with_member]
    assert m['member'] == dict(uuid=member['uuid'], name='Listed')
    assert m['status'] == 'open' and m['age_hours'] == 3 and m['subject'] == SECRET_SUBJECT
    assert m['body_text'] == SECRET_BODY and m['from_address'] == 'sender@ahavah-test.invalid'
    assert m['gmail_url'].startswith(
        'https://mail.google.com/mail/?authuser=admin@techbaseltd.com#search/rfc822msgid%3Aroute-')
    assert m['gmail_url'].endswith('%40mail.ahavah-test.invalid')
    assert rows[without]['member'] is None and rows[without]['preview'] == 'Short note with spaces'


def test_reply_in_gmail_searches_the_owners_mailbox_for_the_message_id(
        client, admin_headers, support_rows, monkeypatch):
    monkeypatch.setenv('AHAVAH_SUPPORT_GMAIL_USER', 'owner@ahavah-test.invalid')
    monkeypatch.setenv('AHAVAH_SUPPORT_MAILBOX', 'support@ahavah.app')
    assert support_inbox.gmail_url(rfc_message_id='<a+b/c@mail.example>', thread_id='t1') == (
        'https://mail.google.com/mail/?authuser=owner@ahavah-test.invalid'
        '#search/rfc822msgid%3Aa%2Bb%2Fc%40mail.example')
    assert support_inbox.gmail_url(rfc_message_id=None, thread_id='t1') ==         'https://mail.google.com/mail/?authuser=support@ahavah.app#all/t1'
    assert support_inbox.gmail_url(rfc_message_id='', thread_id=None) is None

    old = support_rows(source='gmail')
    neither = support_rows(source='none')
    body = client.get(LIST, headers=admin_headers).get_json()
    rows = {m['id']: m for m in body['messages']}
    assert '#all/route-' in rows[old]['gmail_url'] and rows[old]['gmail_url'].endswith('-t')
    assert rows[neither]['gmail_url'] is None


def test_the_status_filter_and_its_order(client, admin_headers, support_rows):
    older, newer = support_rows(hours_old=5), support_rows(hours_old=1)
    handled = support_rows(status='handled')
    open_ids = [m['id'] for m in client.get(f'{LIST}?status=open', headers=admin_headers).get_json()['messages']]
    assert handled not in open_ids
    if older in open_ids and newer in open_ids:
        assert open_ids.index(older) < open_ids.index(newer)  # open: oldest first
    handled_ids = [m['id'] for m in
                   client.get(f'{LIST}?status=handled', headers=admin_headers).get_json()['messages']]
    assert handled in handled_ids and older not in handled_ids
    assert client.get(f'{LIST}?status=closed', headers=admin_headers).status_code == 400
    assert client.get(f'{LIST}?page=abc', headers=admin_headers).status_code == 200


def test_marking_handled_is_audited_once_and_a_second_mark_answers_409(
        client, admin_headers, make_person, support_rows):
    member = make_person(name='Helped')
    mid = support_rows(person_id=member['id'])
    r = client.post(HANDLED.format(mid), headers=admin_headers)
    assert r.status_code == 200
    out = r.get_json()
    assert out['id'] == mid and out['status'] == 'handled' and out['handled_at']
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT status, handled_by, handled_at FROM support_message WHERE id = %(i)s',
                         dict(i=mid)).fetchone()
    assert row['status'] == 'handled' and row['handled_by'] and row['handled_at']

    again = client.post(HANDLED.format(mid), headers=admin_headers)
    assert again.status_code == 409 and again.get_json() == dict(error='already_handled', status='handled')
    assert client.post(NOT_FOR_US.format(mid), headers=admin_headers).status_code == 409

    [audit] = _audits(mid)
    assert audit['action'] == 'support_handled' and str(audit['target_uuid']) == member['uuid']
    assert audit['target_email'] is None
    assert 'ahavah-test.invalid' not in json.dumps(audit['metadata']) and 'SECRET' not in json.dumps(audit['metadata'])


def test_not_for_us(client, admin_headers, support_rows):
    mid = support_rows()
    r = client.post(NOT_FOR_US.format(mid), headers=admin_headers)
    assert r.status_code == 200 and r.get_json()['status'] == 'not_for_us'
    [audit] = _audits(mid)
    assert audit['action'] == 'support_not_for_us' and audit['target_uuid'] is None


def test_an_unknown_message_answers_404(client, admin_headers):
    assert client.post(HANDLED.format(2_000_000_000), headers=admin_headers).status_code == 404
    assert client.post(REOPEN.format(2_000_000_000), headers=admin_headers).status_code == 404


@pytest.mark.parametrize('status', ['handled', 'not_for_us'])
def test_a_closed_message_can_be_reopened_and_it_is_audited(client, admin_headers, make_person,
                                                            support_rows, status):
    member = make_person(name='Reopened')
    mid = support_rows(person_id=member['id'])
    mark = HANDLED if status == 'handled' else NOT_FOR_US
    assert client.post(mark.format(mid), headers=admin_headers).status_code == 200
    r = client.post(REOPEN.format(mid), headers=admin_headers)
    assert r.status_code == 200 and r.get_json() == dict(id=mid, status='open')
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT status, handled_by, handled_at FROM support_message WHERE id = %(i)s',
                         dict(i=mid)).fetchone()
    assert row == dict(status='open', handled_by=None, handled_at=None)
    reopened = [a for a in _audits(mid) if a['action'] == 'support_reopened']
    assert len(reopened) == 1
    assert str(reopened[0]['target_uuid']) == member['uuid'] and reopened[0]['target_email'] is None
    assert reopened[0]['metadata'] == dict(support_message_id=mid, previous=status)
    # Open again, so it can be marked again.
    assert client.post(HANDLED.format(mid), headers=admin_headers).status_code == 200


def test_reopening_an_open_message_answers_409(client, admin_headers, support_rows):
    mid = support_rows()
    r = client.post(REOPEN.format(mid), headers=admin_headers)
    assert r.status_code == 409 and r.get_json() == dict(error='already_open')
    assert _audits(mid) == []


# --- 8. the owner's daily alert --------------------------------------------------------

@pytest.fixture
def guard_mail(monkeypatch):
    with api_tx() as tx:
        tx.execute("DELETE FROM send_guard_event WHERE event = %(e)s", dict(e=sendguard.SUPPORT_ALERT_EVENT))
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_ALERT_EMAILS', 'owner@ahavah-test.invalid')
    out: list[dict] = []
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', lambda self, **kw: out.append(kw) or 'mid')
    monkeypatch.setattr('service.notifications._send_to_user_blocking', lambda *a, **kw: 1)
    monkeypatch.setattr(sendguard, 'FEEDBACK_ALERT_FROM_HOUR', 0)
    monkeypatch.setattr(sendguard, 'FEEDBACK_ALERT_LISTED', 100_000)
    yield out
    with api_tx() as tx:
        tx.execute("DELETE FROM send_guard_event WHERE event = %(e)s", dict(e=sendguard.SUPPORT_ALERT_EVENT))


def test_the_alert_lists_only_messages_open_for_more_than_24_hours(support_rows, guard_mail):
    stale = support_rows(hours_old=30)
    fresh = support_rows(hours_old=2)
    handled = support_rows(hours_old=40, status='handled')
    with api_tx('read committed') as tx:
        [ev] = sendguard.unanswered_support_events(tx, from_hour=0)
    ids = [m['id'] for m in ev['detail']['messages']]
    assert stale in ids and fresh not in ids and handled not in ids
    assert [m for m in ev['detail']['messages'] if m['id'] == stale] == [dict(id=stale, age_hours=30)]

    sendguard.tick()
    [mail] = [m for m in guard_mail if f'message {stale} (30 hours)' in m['body']]
    assert 'support messages have had no answer for more than 24 hours' in mail['body'] \
        or 'support message has had no answer for more than 24 hours' in mail['body']
    for secret in ('SUBJECT-SECRET', 'BODY-SECRET', 'sender', '@', '—', '!'):
        assert secret not in mail['body']

    sent = len(guard_mail)
    sendguard.tick()
    assert len(guard_mail) == sent  # once a day


def test_no_alert_before_the_hour():
    with api_tx('read committed') as tx:
        assert sendguard.unanswered_support_events(tx, from_hour=25) == []


def test_the_alert_copy():
    msgs = [dict(id=i, age_hours=25) for i in range(1, 24)]
    line = sendguard.describe(dict(event=sendguard.SUPPORT_ALERT_EVENT, detail=dict(messages=msgs)))
    assert line.startswith('23 support messages have had no answer for more than 24 hours: message 1 (25 hours)')
    assert 'message 20 (25' in line and 'message 21 (25' not in line and 'and 3 more' in line
    assert line.endswith('Reply in Gmail, then mark each one handled or not for us on the Support tab.')
    one = sendguard.describe(dict(event=sendguard.SUPPORT_ALERT_EVENT, detail=dict(messages=msgs[:1])))
    assert one.startswith('1 support message has had no answer')
    assert sendguard._alert_text([dict(event=sendguard.SUPPORT_ALERT_EVENT, detail=dict(messages=msgs))],
                                 last=False)[0] == 'Ahavah: support messages with no answer'
    both = [dict(event=sendguard.SUPPORT_ALERT_EVENT, detail=dict(messages=msgs)),
            dict(event=sendguard.FEEDBACK_ALERT_EVENT, detail=dict(reports=[]))]
    assert sendguard._alert_text(both, last=False)[0] == \
        'Ahavah: member reports and support messages with no answer'


# --- 9. retention and the migration ------------------------------------------------------

def test_copies_are_deleted_a_year_after_they_arrived(support_rows):
    old = support_rows(hours_old=366 * 24)
    kept = support_rows(hours_old=300 * 24)
    with api_tx() as tx:
        assert support_inbox.purge_old(tx) >= 1
        left = {r['id'] for r in tx.execute('SELECT id FROM support_message WHERE id = ANY(%(i)s)',
                                            dict(i=[old, kept])).fetchall()}
    assert left == {kept}


def test_the_retention_cron_runs_the_sweep(support_rows, capsys):
    from service.cron.leadretention import _purge_once
    old = support_rows(hours_old=400 * 24)
    _purge_once()
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM support_message WHERE id = %(i)s', dict(i=old)).fetchone() is None
    assert 'support message(s) deleted 365 days after they arrived' in capsys.readouterr().out


def test_the_migrations_run_twice():
    for _ in range(2):
        for path in MIGRATIONS:
            with api_tx() as tx:
                tx.execute(path.read_text(encoding='utf-8'))


def test_a_resend_id_is_stored_once_by_the_database_too():
    import psycopg
    rid = f'dup-{uuid4().hex}'
    insert = """INSERT INTO support_message (resend_email_id, from_address, received_at)
                VALUES (%(r)s, 'a@ahavah-test.invalid', NOW())"""
    try:
        with api_tx() as tx:
            tx.execute(insert, dict(r=rid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute(insert, dict(r=rid))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM support_message WHERE resend_email_id = %(r)s', dict(r=rid))


def test_the_body_cap_is_enforced_by_the_database_too():
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("""INSERT INTO support_message (gmail_message_id, gmail_thread_id, from_address,
                                                       body_text, received_at)
                          VALUES (%(m)s, 't', 'a@ahavah-test.invalid', %(b)s, NOW())""",
                       dict(m=f'cap-{uuid4().hex}', b='x' * 20_001))


def test_an_imported_open_message_is_overdue_24_hours_after_it_was_copied(support_rows):
    just_copied = support_rows(hours_old=10 * 24, copied_hours_old=1)
    copied_a_day_ago = support_rows(hours_old=10 * 24, copied_hours_old=25)
    with api_tx('read committed') as tx:
        stale = {m['id']: m['age_hours'] for m in support_admin.stale_open(tx)}
    assert just_copied not in stale and stale[copied_a_day_ago] == 25



# --- 12. the send guard's tick ----------------------------------------------------------------

def test_the_tick_reads_no_support_message_while_the_switch_is_off(guard_mail, monkeypatch):
    monkeypatch.delenv('AHAVAH_SUPPORT_INBOX_ENABLED', raising=False)

    def boom(*a, **kw):
        raise AssertionError('read while off')

    monkeypatch.setattr(sendguard, 'unanswered_support_events', boom)
    monkeypatch.setattr('service.support_inbox.admin.stale_open', boom)
    assert 'events' in sendguard.tick()


def test_a_failed_support_read_does_not_break_the_tick(guard_mail, monkeypatch, capsys):
    def poisoned(tx, **kw):
        tx.execute('SELECT 1 FROM no_such_support_table')

    monkeypatch.setattr('service.support_inbox.admin.stale_open', poisoned)
    out = sendguard.tick()
    assert 'events' in out
    assert 'support reminder skipped (UndefinedTable)' in capsys.readouterr().out


# --- 11. one bad message --------------------------------------------------------------------

def test_a_message_resend_cannot_find_is_skipped_by_id_and_the_pass_moves_on(inbox, capsys):
    first, gone, good = inbox.ids(3)
    client = FakeResend([inbox.mail(first)])
    inbox.run(client)
    client.deliver(inbox.mail(gone))
    client.deliver(inbox.mail(good))
    client.fail_ids[gone] = support_inbox.ResendError(404)
    out = inbox.run(client)
    assert out['stored'] == 1 and out['failed_ids'] == [gone]
    st = _state(inbox.mailbox)
    assert st['last_error'] == f'1 message(s) could not be read and were skipped: Resend ids {gone}'
    assert _stored([first, gone, good]) == {first, good}
    printed = capsys.readouterr().out
    assert '1 could not be read' in printed and gone not in printed and 'SECRET' not in printed

    # Not asked for again, and the note stays through a clean pass, so the
    # admin still sees it.
    fetched = len(client.fetched)
    inbox.run(client)
    assert len(client.fetched) == fetched
    assert _state(inbox.mailbox)['last_error'].startswith('1 message(s) could not be read')


def test_a_message_that_cannot_be_parsed_or_stored_is_skipped(inbox, monkeypatch):
    broken, unstorable, good = inbox.ids(3)
    client = FakeResend([inbox.mail(broken), inbox.mail(unstorable), inbox.mail(good)])
    real_get = client.get_received

    def get_received(email_id):
        email = dict(real_get(email_id))
        if email_id == broken:
            email['created_at'] = 'not a time'
        return email

    client.get_received = get_received
    real_store = support_inbox.store

    def store(tx, p, **kw):
        if p.email_id == unstorable:
            tx.execute('SELECT 1 FROM no_such_table')
        return real_store(tx, p, **kw)

    monkeypatch.setattr(support_inbox, 'store', store)
    out = inbox.run(client)
    assert out['stored'] == 1 and sorted(out['failed_ids']) == sorted([broken, unstorable])
    assert out['backfill_done'] is True
    assert _stored([broken, unstorable, good]) == {good}
    st = _state(inbox.mailbox)
    assert '2 message(s) could not be read' in st['last_error'] and 'SECRET' not in st['last_error']


def test_any_other_resend_error_still_fails_the_pass(inbox):
    first, later = inbox.ids(2)
    client = FakeResend([inbox.mail(first)])
    inbox.run(client)
    client.deliver(inbox.mail(later))
    client.fail_ids[later] = support_inbox.ResendError(500)
    assert inbox.run(client) == {'error': 'ResendError 500'}
    del client.fail_ids[later]
    assert inbox.run(client)['stored'] == 1


def test_a_connection_error_is_recorded_by_class_name_only(inbox):
    import requests
    client = FakeResend([])
    client.fail = requests.ConnectionError('https://api.resend.com/emails/receiving?after=secret-id')
    assert inbox.run(client) == {'error': 'ConnectionError'}
    assert _state(inbox.mailbox)['last_error'] == 'ConnectionError'


# --- 12. the first read -----------------------------------------------------------------------

def test_mail_older_than_14_days_before_the_first_pass_comes_in_handled(inbox):
    now = datetime.now(timezone.utc)
    old, recent, later = inbox.ids(3)
    client = FakeResend([inbox.mail(old, received=now - timedelta(days=20)),
                         inbox.mail(recent, received=now - timedelta(days=10))])
    inbox.run(client, now=now)
    rows = {r['resend_email_id']: r for r in _rows([old, recent])}
    assert rows[old]['status'] == 'handled' and rows[old]['handled_by'] == 'Imported'
    assert rows[old]['handled_at'] is not None
    assert rows[recent]['status'] == 'open' and rows[recent]['handled_by'] is None
    first_pass = _state(inbox.mailbox)['first_pass_at']

    # Later passes keep the first pass's date; new mail comes in open.
    client.deliver(inbox.mail(later))
    inbox.run(client, now=now + timedelta(days=30))
    assert _state(inbox.mailbox)['first_pass_at'] == first_pass
    assert _rows([later])[0]['status'] == 'open'


def test_the_list_shows_imported_messages_as_imported(client, admin_headers, inbox):
    [mid] = inbox.ids(1)
    inbox.run(FakeResend([inbox.mail(mid, received=datetime.now(timezone.utc) - timedelta(days=25))]))
    body = client.get(f'{LIST}?status=handled', headers=admin_headers).get_json()
    [m] = [m for m in body['messages']
           if m['gmail_url'] and m['gmail_url'].endswith(f'%3A{mid}%40mail.ahavah-test.invalid')]
    assert m['status'] == 'handled' and m['handled_by'] == 'Imported' and m['handled_by_name'] is None


# --- 13. who handled it, and the summary ----------------------------------------------------------

def test_the_list_names_the_admin_who_handled_a_message(client, admin_headers, make_person, support_rows):
    tag = uuid4().hex[:8]
    # As production holds it: normalized_email is normalize_email(email).
    make_person(name='Miriam Cohen', email=f'miriam.{tag}@ahavah-test.invalid')
    by_admin = support_rows(status='handled')
    by_nobody = support_rows(status='handled')
    with api_tx() as tx:
        tx.execute('UPDATE support_message SET handled_by = %(b)s, handled_at = NOW() WHERE id = %(i)s',
                   dict(b=f'  Miriam.{tag}@AHAVAH-test.invalid ', i=by_admin))
        tx.execute("UPDATE support_message SET handled_by = 'Imported', handled_at = NOW() WHERE id = %(i)s",
                   dict(i=by_nobody))
    still_open = support_rows()
    body = client.get(LIST, headers=admin_headers).get_json()
    rows = {m['id']: m for m in body['messages']}
    assert rows[by_admin]['handled_by_name'] == 'Miriam'
    assert rows[by_admin]['handled_by'] == f'  Miriam.{tag}@AHAVAH-test.invalid '
    assert rows[by_nobody]['handled_by_name'] is None and rows[by_nobody]['handled_by'] == 'Imported'
    assert rows[still_open]['handled_by_name'] is None


def test_marking_through_the_route_names_the_admin(client, admin_headers, support_rows):
    mid = support_rows()
    assert client.post(HANDLED.format(mid), headers=admin_headers).status_code == 200
    body = client.get(f'{LIST}?status=handled', headers=admin_headers).get_json()
    [m] = [m for m in body['messages'] if m['id'] == mid]
    with api_tx('read committed') as tx:
        admin = tx.execute("SELECT split_part(name, ' ', 1) AS first FROM person "
                           "WHERE lower(email) = lower(%(e)s)", dict(e=m['handled_by'])).fetchone()
    assert m['handled_by_name'] == (admin['first'] if admin and admin['first'] else None)


SUMMARY = '/admin/support/summary'


def test_the_summary_is_admin_only(client, make_person, sign_in):
    member = sign_in(make_person(name='NotAdminEither'))
    assert client.get(SUMMARY, headers=member).status_code == 403
    assert client.get(SUMMARY).status_code in (400, 401, 403)


def test_the_summary_holds_counts_and_the_inbox_and_no_message(client, admin_headers, support_rows,
                                                                 monkeypatch):
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', '1')
    before = client.get(SUMMARY, headers=admin_headers).get_json()
    support_rows()
    support_rows(status='not_for_us')
    r = client.get(SUMMARY, headers=admin_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {'counts', 'inbox'}
    assert set(body['counts']) == {'open', 'handled', 'not_for_us'}
    assert set(body['inbox']) == {'enabled', 'mailbox', 'last_checked_at', 'last_ok_at', 'last_error',
                                  'backfill_done'}
    assert body['inbox']['enabled'] is True
    assert body['counts']['open'] == before['counts']['open'] + 1
    assert body['counts']['not_for_us'] == before['counts']['not_for_us'] + 1
    text = r.get_data(as_text=True)
    for secret in ('SUBJECT-SECRET', 'BODY-SECRET', 'sender@', 'Sender'):
        assert secret not in text
    # The same counts and inbox block as the list.
    listed = client.get(LIST, headers=admin_headers).get_json()
    assert listed['counts'] == body['counts'] and listed['inbox'] == body['inbox']
