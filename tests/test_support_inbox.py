"""Support messages in the admin (TEC-2115,
docs/plans/2026-11-05-support-messages-in-admin.md).

Rules locked in here:
  1. Off by default: with the switch off, or on with no key file, a pass
     reads nothing and stores nothing, and says so at most once.
  2. A new message is stored once; a replay, a second pass and a backfill
     that runs again store nothing more.
  3. Mail the mailbox sent, automatic replies, spam and mail older than the
     year kept are skipped.
  4. The member is matched by normalised email, and only when exactly one
     account matches.
  5. HTML-only mail is stored as plain text; every body is capped at 20,000
     characters.
  6. Nothing printed names a sender, a subject or a body: counts and an
     error's class name only.
  7. The admin routes are admin only; marking is audited, once, and a second
     mark answers 409.
  8. The owner's daily alert lists open messages older than 24 hours by
     number and age only, once a day.
  9. Copies are deleted a year after they arrived.

No test calls Google: every pass gets a fake client.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import smtp as smtp_mod
from database import api_tx
from service import sendguard, support_inbox
from service.support_inbox import admin as support_admin

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0093_support_messages.sql'
SECRET_SUBJECT = 'Please unlock my account SUBJECT-SECRET'
SECRET_BODY = 'My account is locked. BODY-SECRET'


def _b64(text: str, charset: str = 'utf-8') -> str:
    return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip('=')


def gmsg(mid: str, *, frm: str = 'Rivka Levi <rivka@ahavah-test.invalid>', subject: str = SECRET_SUBJECT,
         text: str | None = SECRET_BODY, html: str | None = None, labels=('INBOX', 'UNREAD'),
         extra_headers: dict | None = None, received: datetime | None = None,
         thread: str | None = None) -> dict:
    received = received or datetime.now(timezone.utc) - timedelta(minutes=3)
    parts = []
    if text is not None:
        parts.append(dict(mimeType='text/plain', filename='',
                          headers=[dict(name='Content-Type', value='text/plain; charset="UTF-8"')],
                          body=dict(data=_b64(text))))
    if html is not None:
        parts.append(dict(mimeType='text/html', filename='',
                          headers=[dict(name='Content-Type', value='text/html; charset=UTF-8')],
                          body=dict(data=_b64(html))))
    parts.append(dict(mimeType='application/pdf', filename='scan.pdf', headers=[],
                      body=dict(attachmentId='att-1', size=1000)))
    headers = [dict(name='From', value=frm), dict(name='Subject', value=subject),
               dict(name='To', value='support@ahavah.app')]
    headers += [dict(name=k, value=v) for k, v in (extra_headers or {}).items()]
    return dict(id=mid, threadId=thread or f'{mid}-t', labelIds=list(labels),
                internalDate=str(int(received.timestamp() * 1000)),
                payload=dict(mimeType='multipart/mixed', headers=headers, body=dict(size=0), parts=parts))


class FakeGmail:
    """The four calls the pass makes, over an in-memory mailbox. Pages of 2
    so the backfill's page token is exercised."""

    def __init__(self, messages: list[dict], history_id: str = '1000'):
        self.messages = {m['id']: m for m in messages}
        self.history_id = history_id
        self.added: list[dict] = []
        self.expired = False
        self.fetched: list[str] = []
        self.fail: Exception | None = None

    def current_history_id(self) -> str:
        if self.fail:
            raise self.fail
        return self.history_id

    def list_message_ids(self, page_token):
        ids = list(self.messages)
        start = int(page_token or 0)
        nxt = start + 2
        return ids[start:nxt], (str(nxt) if nxt < len(ids) else None)

    def history(self, start_history_id, page_token):
        if self.fail:
            raise self.fail
        if self.expired:
            raise support_inbox.HistoryExpired()
        return list(self.added), None, self.history_id

    def get_message(self, message_id):
        self.fetched.append(message_id)
        return self.messages[message_id]

    def deliver(self, msg: dict) -> None:
        """A message arrives: in the mailbox, and in the history."""
        self.messages[msg['id']] = msg
        self.added.append(dict(id=msg['id'], labelIds=msg['labelIds']))
        self.history_id = str(int(self.history_id) + 1)


@pytest.fixture
def inbox(monkeypatch):
    """The switch on, a mailbox of this test's own, and every row it made
    deleted afterwards. `inbox.ids(n)` gives Gmail ids no other run uses."""
    tag = uuid4().hex[:10]
    box = f'support-{tag}@ahavah-test.invalid'
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_SUPPORT_MAILBOX', box)
    monkeypatch.setattr(support_inbox, '_said_no_key', False)

    class _Inbox:
        mailbox = box

        @staticmethod
        def ids(n: int) -> list[str]:
            return [f'{tag}-{i}' for i in range(n)]

        @staticmethod
        def run(client, now=None) -> dict:
            return support_inbox.tick(make_client=lambda path, mb: client, now=now)

    yield _Inbox
    with api_tx() as tx:
        tx.execute('DELETE FROM support_message WHERE gmail_message_id LIKE %(p)s', dict(p=f'{tag}-%'))
        tx.execute('DELETE FROM support_inbox_state WHERE mailbox = %(m)s', dict(m=box))


def _rows(tag_ids: list[str]) -> list[dict]:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM support_message WHERE gmail_message_id = ANY(%(i)s) ORDER BY id',
                          dict(i=tag_ids)).fetchall()


def _state(box: str) -> dict | None:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM support_inbox_state WHERE mailbox = %(m)s', dict(m=box)).fetchone()


# --- 1. off by default --------------------------------------------------------

def test_the_switch_is_off_unless_set(monkeypatch, capsys):
    monkeypatch.delenv('AHAVAH_SUPPORT_INBOX_ENABLED', raising=False)
    called = []
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'off': True}
    monkeypatch.setenv('AHAVAH_SUPPORT_INBOX_ENABLED', 'yes please')
    assert support_inbox.tick(make_client=lambda *a: called.append(a)) == {'off': True}
    assert called == [] and capsys.readouterr().out == ''


def test_on_with_no_key_file_checks_nothing_and_says_so_once(inbox, monkeypatch, capsys):
    monkeypatch.setenv('AHAVAH_SUPPORT_GMAIL_KEY_PATH', '/nonexistent/support-gmail.json')
    assert support_inbox.tick() == {'no_key': True}
    assert support_inbox.tick() == {'no_key': True}
    out = capsys.readouterr().out
    assert out.count('support_inbox:') == 1 and 'no key file' in out
    assert _state(inbox.mailbox) is None


def test_the_defaults():
    assert support_inbox.DEFAULT_MAILBOX == 'support@ahavah.app'
    assert support_inbox.SCOPE == 'https://www.googleapis.com/auth/gmail.readonly'
    text = (Path(__file__).resolve().parent.parent / 'docker-compose.production.yml').read_text()
    assert text.count('AHAVAH_SUPPORT_INBOX_ENABLED: ${AHAVAH_SUPPORT_INBOX_ENABLED:-0}') == 2
    assert 'DUO_CRON_SUPPORT_INBOX_POLL_SECONDS: ${DUO_CRON_SUPPORT_INBOX_POLL_SECONDS:-300}' in text
    assert '/opt/ahavah-secrets:/run/ahavah-secrets:ro' in text


# --- 2. stored once -----------------------------------------------------------

def test_the_first_pass_reads_the_whole_mailbox_and_stores_each_message_once(inbox, capsys):
    ids = inbox.ids(5)
    client = FakeGmail([gmsg(i) for i in ids])
    out = inbox.run(client)
    # 3 pages of 2 per pass: the whole mailbox of 5 in one pass.
    assert out['stored'] == 5 and out['backfill_done'] is True
    assert [r['gmail_message_id'] for r in _rows(ids)] == ids
    st = _state(inbox.mailbox)
    assert st['history_id'] == '1000' and st['backfill_done'] and st['last_ok_at'] and st['last_error'] is None

    fetched = len(client.fetched)
    out = inbox.run(client)
    assert out['stored'] == 0 and len(client.fetched) == fetched  # nothing fetched again
    assert len(_rows(ids)) == 5
    printed = capsys.readouterr().out
    assert '5 new message(s) copied' in printed


def test_a_long_backfill_carries_on_in_the_next_pass(inbox, monkeypatch):
    monkeypatch.setattr(support_inbox, 'BACKFILL_PAGES_PER_PASS', 1)
    ids = inbox.ids(5)
    client = FakeGmail([gmsg(i) for i in ids])
    assert inbox.run(client)['stored'] == 2
    assert _state(inbox.mailbox)['backfill_token'] == '2'
    assert inbox.run(client)['stored'] == 2
    out = inbox.run(client)
    assert out['stored'] == 1 and out['backfill_done'] is True
    assert len(_rows(ids)) == 5


def test_new_mail_arrives_through_the_history_and_replays_are_ignored(inbox):
    first, second = inbox.ids(2)
    client = FakeGmail([gmsg(first)])
    inbox.run(client)
    client.deliver(gmsg(second))
    out = inbox.run(client)
    assert out['stored'] == 1
    assert _state(inbox.mailbox)['history_id'] == '1001'
    # The same history again (a replay): nothing new.
    client.added.append(dict(id=second, labelIds=['INBOX']))
    assert inbox.run(client)['stored'] == 0
    assert [r['gmail_message_id'] for r in _rows([first, second])] == [first, second]


def test_a_history_too_old_starts_the_full_read_again_without_duplicates(inbox, capsys):
    a, b = inbox.ids(2)
    client = FakeGmail([gmsg(a)])
    inbox.run(client)
    client.messages[b] = gmsg(b)  # arrived while history was lost
    client.history_id = '5000'
    client.expired = True
    out = inbox.run(client)
    assert out['restarted'] == 1 and out['stored'] == 1
    assert _state(inbox.mailbox)['history_id'] == '5000'
    assert len(_rows([a, b])) == 2
    assert 'started again' in capsys.readouterr().out


# --- 3. skipped -----------------------------------------------------------------

def test_own_mail_automatic_replies_spam_and_old_mail_are_skipped(inbox, monkeypatch):
    monkeypatch.setattr(support_inbox, 'BACKFILL_PAGES_PER_PASS', 10)
    keep, own_from, sent, spam, auto, autoreply, prec, daemon, old = inbox.ids(9)
    client = FakeGmail([
        gmsg(keep),
        gmsg(own_from, frm=f'Ahavah Support <{inbox.mailbox.upper()}>'),
        gmsg(sent, labels=('SENT',)),
        gmsg(spam, labels=('SPAM',)),
        gmsg(auto, extra_headers={'Auto-Submitted': 'auto-replied'}),
        gmsg(autoreply, extra_headers={'X-Autoreply': 'yes'}),
        gmsg(prec, extra_headers={'Precedence': 'auto_reply'}),
        gmsg(daemon, frm='Mail Delivery Subsystem <mailer-daemon@googlemail.com>'),
        gmsg(old, received=datetime.now(timezone.utc) - timedelta(days=400)),
    ])
    out = inbox.run(client)
    assert out['stored'] == 1 and out['skipped'] == 8
    assert [r['gmail_message_id'] for r in _rows(inbox.ids(9))] == [keep]


def test_mail_the_mailbox_sent_is_skipped_from_the_history_without_fetching_it(inbox):
    first, reply = inbox.ids(2)
    client = FakeGmail([gmsg(first)])
    inbox.run(client)
    client.deliver(gmsg(reply, labels=('SENT',), frm=inbox.mailbox))
    fetched = len(client.fetched)
    out = inbox.run(client)
    assert out['stored'] == 0 and out['skipped'] == 1 and len(client.fetched) == fetched


def test_an_explicit_auto_submitted_no_is_kept(inbox):
    [mid] = inbox.ids(1)
    inbox.run(FakeGmail([gmsg(mid, extra_headers={'Auto-Submitted': 'no'})]))
    assert len(_rows([mid])) == 1


# --- 4. the member ----------------------------------------------------------------

def test_the_member_is_matched_by_normalised_email(inbox, make_person):
    tag = uuid4().hex[:8]
    member = make_person(name='Rivka', email=f'rivka{tag}@gmail.com')
    matched, stranger = inbox.ids(2)
    inbox.run(FakeGmail([
        gmsg(matched, frm=f'Rivka <Rivka.{tag}+support@GoogleMail.com>'),
        gmsg(stranger, frm='Nobody <nobody-at-all@ahavah-test.invalid>'),
    ]))
    rows = {r['gmail_message_id']: r for r in _rows([matched, stranger])}
    assert rows[matched]['person_id'] == member['id']
    assert rows[matched]['from_address'] == f'rivka.{tag}+support@googlemail.com'
    assert rows[matched]['from_name'] == 'Rivka'
    assert rows[stranger]['person_id'] is None


# --- 5. the text ------------------------------------------------------------------

def test_html_only_mail_is_stored_as_plain_text_and_bodies_are_capped(inbox):
    html_id, long_id = inbox.ids(2)
    html = ('<html><head><style>p{color:red}</style><title>t</title></head><body>'
            '<p>Shalom,</p><p>My account&nbsp;is <b>locked</b>.<br>Please help &amp; thanks</p>'
            '<script>alert(1)</script></body></html>')
    inbox.run(FakeGmail([gmsg(html_id, text=None, html=html), gmsg(long_id, text='x' * 30_000)]))
    rows = {r['gmail_message_id']: r for r in _rows([html_id, long_id])}
    assert rows[html_id]['body_text'] == 'Shalom,\n\nMy account is locked.\nPlease help & thanks'
    assert len(rows[long_id]['body_text']) == 20_000


def test_encoded_headers_and_other_charsets_are_read():
    hebrew = 'Shalom עזרה'
    msg = gmsg('x', subject='=?utf-8?b?' + base64.b64encode(hebrew.encode()).decode() + '?=',
               frm='=?utf-8?q?Ren=C3=A9e?= <renee@ahavah-test.invalid>', text=None)
    msg['payload']['parts'].insert(0, dict(
        mimeType='text/plain', filename='',
        headers=[dict(name='Content-Type', value='text/plain; charset=iso-8859-1')],
        body=dict(data=_b64('Café \x00ok', 'iso-8859-1'))))
    p = support_inbox.parse(msg)
    assert p.subject == hebrew and p.from_name == 'Renée'
    assert p.from_address == 'renee@ahavah-test.invalid' and p.body_text == 'Café ok'


# --- 6. nothing personal in the log ------------------------------------------------

def test_a_failed_pass_records_the_error_class_and_prints_it_once(inbox, capsys):
    [mid] = inbox.ids(1)
    client = FakeGmail([gmsg(mid)])
    inbox.run(client)
    client.fail = support_inbox.GmailError(403)
    assert inbox.run(client) == {'error': 'GmailError 403'}
    assert inbox.run(client) == {'error': 'GmailError 403'}
    st = _state(inbox.mailbox)
    assert st['last_error'] == 'GmailError 403' and st['last_checked_at'] > st['last_ok_at']
    out = capsys.readouterr().out
    assert out.count('check failed (GmailError 403)') == 1
    client.fail = None
    inbox.run(client)
    assert _state(inbox.mailbox)['last_error'] is None


def test_nothing_printed_names_a_sender_a_subject_or_a_body(inbox, capsys):
    ids = inbox.ids(3)
    client = FakeGmail([gmsg(i) for i in ids])
    inbox.run(client)
    client.fail = ValueError(f'{SECRET_SUBJECT} rivka@ahavah-test.invalid')
    inbox.run(client)
    out = capsys.readouterr().out
    assert out
    for secret in ('SUBJECT-SECRET', 'BODY-SECRET', 'rivka', '@', inbox.mailbox):
        assert secret not in out


# --- 7. the admin routes --------------------------------------------------------------

LIST = '/admin/support/messages'
HANDLED = '/admin/support/messages/{}/handled'
NOT_FOR_US = '/admin/support/messages/{}/not-for-us'
REOPEN = '/admin/support/messages/{}/reopen'


@pytest.fixture
def support_rows():
    made: list[int] = []

    def _make(*, hours_old: int = 1, person_id=None, status='open', subject=SECRET_SUBJECT,
              body=SECRET_BODY) -> int:
        mid = f'route-{uuid4().hex}'
        with api_tx() as tx:
            rid = tx.execute(
                """INSERT INTO support_message (gmail_message_id, gmail_thread_id, from_address, from_name,
                                                subject, body_text, received_at, person_id, status)
                   VALUES (%(m)s, %(t)s, 'sender@ahavah-test.invalid', 'Sender', %(s)s, %(b)s,
                           NOW() - make_interval(hours => %(h)s), %(p)s, %(st)s)
                   RETURNING id""",
                dict(m=mid, t=f'{mid}-t', s=subject, b=body, h=hours_old, p=person_id, st=status),
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
    assert m['gmail_url'].startswith('https://mail.google.com/mail/?authuser=')
    assert '#all/route-' in m['gmail_url']
    assert rows[without]['member'] is None and rows[without]['preview'] == 'Short note with spaces'


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


def test_the_migration_runs_twice():
    for _ in range(2):
        with api_tx() as tx:
            tx.execute(MIGRATION.read_text(encoding='utf-8'))


def test_the_body_cap_is_enforced_by_the_database_too():
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("""INSERT INTO support_message (gmail_message_id, gmail_thread_id, from_address,
                                                       body_text, received_at)
                          VALUES (%(m)s, 't', 'a@ahavah-test.invalid', %(b)s, NOW())""",
                       dict(m=f'cap-{uuid4().hex}', b='x' * 20_001))
