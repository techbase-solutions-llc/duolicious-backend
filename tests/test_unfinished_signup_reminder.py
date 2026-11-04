"""The unfinished sign-up reminder (TEC-2107): one email, once per address
ever, to someone who confirmed their address and started sign-up but has no
account, behind its own switch, at most 20 a Barbados day.

The suite shares one database, so the job runs at a moment years ahead
(NOW): only this module's onboardees fall inside its window, and its daily
count meets only this module's claims. Every row a test makes is removed
afterwards, outbox rows included (an older migration re-run elsewhere in
the suite would refuse an onboardee row left behind)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from database import api_tx
from emails import unfinished_signup as us
from service.campaigns import outbox
from service.unsubscribe import make_token

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0092_unfinished_signup.sql'
SWITCH_ENV = 'AHAVAH_UNFINISHED_SIGNUP_REMINDER_ENABLED'

MONDAY = datetime(2031, 6, 2, 13, tzinfo=timezone.utc)   # 09:00 in Barbados
NOW = MONDAY


@pytest.fixture(autouse=True, scope='module')
def _schema():
    """0092 again: a migration test earlier in the run (0066, 0071, 0073)
    re-applies an older outbox check that has no onboardee_email."""
    with api_tx() as tx:
        tx.execute(MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(SWITCH_ENV, '1')


@pytest.fixture
def made():
    """onboardee(...) makes one unfinished sign-up, idle for `hours` before
    `now`, and returns its address. Everything the address gathers is
    removed afterwards."""
    emails: list[str] = []

    def _make(*, hours: float = 30, now: datetime = NOW, email: str | None = None,
              name: str | None = 'Tirzah', lead_source=None) -> str:
        email = email or f'uf-{uuid4().hex[:10]}@ahavah-test.invalid'
        with api_tx() as tx:
            tx.execute("""INSERT INTO onboardee (email, name, lead_source, created_at, updated_at)
                          VALUES (%(e)s, %(n)s, %(ls)s, %(at)s, %(at)s)""",
                       dict(e=email, n=name, ls=lead_source,
                            at=now - timedelta(hours=hours)))
        emails.append(email.lower())
        return email

    _make.emails = emails
    yield _make
    with api_tx() as tx:
        tx.execute("DELETE FROM email_outbox WHERE onboardee_email = ANY(%(e)s)", dict(e=emails))
        tx.execute("DELETE FROM lead_email_send WHERE email = ANY(%(e)s)", dict(e=emails))
        tx.execute("DELETE FROM onboardee WHERE lower(email) = ANY(%(e)s)", dict(e=emails))
        tx.execute("DELETE FROM lead WHERE lower(email) = ANY(%(e)s)", dict(e=emails))


def _run(now: datetime = NOW) -> int:
    with api_tx() as tx:
        return us.queue_due(tx, now)


def _rows(emails) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT onboardee_email, email, campaign, campaign_id, state, unsub_scope, exempt,
                      last_error, payload->>'subject' AS subject, payload->>'html' AS html,
                      payload->>'list_unsubscribe' AS list_unsubscribe
                 FROM email_outbox WHERE onboardee_email = ANY(%(e)s) ORDER BY id""",
            dict(e=[e.lower() for e in emails])).fetchall()]


def _claim(email) -> dict | None:
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT * FROM lead_email_send WHERE email = %(e)s AND campaign = 'unfinished_signup'",
                         dict(e=email.lower())).fetchone()
    return dict(row) if row else None


class _Smtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


def _drain(emails) -> _Smtp:
    """Drain only these addresses' rows: every other due row is parked, as
    the conftest outbox_drain does for members."""
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued'
                         AND (onboardee_email IS NULL OR NOT (onboardee_email = ANY(%(e)s)))""",
                   dict(e=[e.lower() for e in emails]))
    smtp = _Smtp()
    outbox.drain(api_tx, smtp)
    return smtp


# ---------------------------------------------------------------------------
# the switch and the window
# ---------------------------------------------------------------------------

def test_the_switch_is_off_by_default_and_then_nothing_is_queued(made, monkeypatch):
    monkeypatch.delenv(SWITCH_ENV, raising=False)
    e = made()
    assert _run() == 0
    assert _rows([e]) == [] and _claim(e) is None


def test_the_returnmail_cron_runs_it():
    from service.cron.returnmail import JOBS
    assert ('unfinished_signup', us.queue_due) in JOBS


def test_the_migration_runs_twice():
    sql = MIGRATION.read_text(encoding='utf-8')
    assert "SET lock_timeout = '5s';" in sql and 'RESET lock_timeout;' in sql
    with api_tx() as tx:
        tx.execute(sql)
        tx.execute(sql)


def test_due_between_24_hours_and_14_days(made, on):
    e23, e25 = made(hours=23), made(hours=25)
    e13d, e15d = made(hours=13 * 24), made(hours=15 * 24)
    assert _run() == 2
    assert {r['onboardee_email'] for r in _rows([e23, e25, e13d, e15d])} == {e25, e13d}


def test_nothing_on_friday_or_saturday_or_before_noon_utc(made, on):
    e = made()
    friday = datetime(2031, 6, 6, 13, tzinfo=timezone.utc)
    made(now=friday)
    assert _run(friday) == 0 and _run(friday + timedelta(days=1)) == 0
    assert _run(MONDAY.replace(hour=11)) == 0
    assert _rows(made.emails) == []
    assert _run() == 1 and [r['onboardee_email'] for r in _rows([e])] == [e]


def test_a_tool_visitor_who_saved_no_step_is_not_reminded(made, on):
    tool_only = made(name=None, lead_source='tool:game-us')
    started = made(name='Started', lead_source='tool:checklist')
    made_nothing = made(name=None)
    _run()
    assert {r['onboardee_email'] for r in _rows(made.emails)} == {started, made_nothing}
    assert _rows([tool_only]) == []


# ---------------------------------------------------------------------------
# who is left out
# ---------------------------------------------------------------------------

def test_an_account_with_the_same_address_in_another_case_stops_it(made, on, make_person):
    e = made()
    p = make_person(name='Finished')
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(n)s WHERE id = %(i)s",
                   dict(e=e.upper(), n=e.lower(), i=p['id']))
    assert _run() == 0 and _rows([e]) == [] and _claim(e) is None


def test_staff_and_test_addresses_are_left_out(made, on, monkeypatch):
    e = made()
    monkeypatch.setenv('AHAVAH_TEST_ACCOUNT_EMAILS', e.upper())
    assert _run() == 0 and _rows([e]) == []


def test_a_suppressed_address_is_left_out(made, on):
    e = made(email=f'uf-{uuid4().hex[:10]}@example.com')
    assert _run() == 0 and _rows([e]) == [] and _claim(e) is None


def test_an_address_that_left_the_news_mail_is_left_out(made, on):
    e = made()
    with api_tx() as tx:
        tx.execute("""INSERT INTO lead (email, normalized_email, source, unsubscribed_at)
                      VALUES (%(e)s, %(e)s, 'tool:checklist', NOW())""", dict(e=e))
    assert _run() == 0 and _rows([e]) == [] and _claim(e) is None


# ---------------------------------------------------------------------------
# once per address, ever, and the cap
# ---------------------------------------------------------------------------

def test_a_second_tick_queues_nothing_more(made, on):
    e = made()
    assert _run() == 1
    assert _run() == 0 and _run(NOW + timedelta(days=1)) == 0
    rows = _rows([e])
    assert len(rows) == 1
    r = rows[0]
    assert (r['campaign'], r['campaign_id'], r['unsub_scope'], r['exempt']) == \
        ('unfinished_signup', 'once', 'signup', False)
    assert r['subject'] == 'Your Ahavah sign-up is waiting'
    assert make_token('signup', e) in r['list_unsubscribe']
    claim = _claim(e)
    assert claim['claimed_at'] == NOW and claim['sent_at'] is None


def test_two_ticks_at_once_queue_one_email(made, on):
    """Tick A holds its transaction open with the claim written; tick B
    runs meanwhile and queues nothing; a third tick after A commits queues
    nothing either."""
    e = made()
    a_queued = threading.Event()
    b_done = threading.Event()
    results: dict = {}

    def tick_a():
        with api_tx() as tx:
            results['a'] = us.queue_due(tx, NOW)
            a_queued.set()
            b_done.wait(10)

    def tick_b():
        a_queued.wait(10)
        try:
            results['b'] = _run()
        except Exception as exc:  # a refusal is also one email in total
            results['b'] = exc
        b_done.set()

    ta, tb = threading.Thread(target=tick_a), threading.Thread(target=tick_b)
    ta.start(); tb.start()
    ta.join(20); tb.join(20)
    assert results['a'] == 1 and results['b'] == 0
    assert _run() == 0
    assert len(_rows([e])) == 1


def test_at_most_20_a_barbados_day_and_the_rest_wait(made, on):
    for i in range(22):
        made(hours=30 + i)
    assert _run() == 20
    assert _run(NOW + timedelta(hours=5)) == 0, 'the same Barbados day'
    tuesday = NOW + timedelta(days=1)
    assert _run(tuesday) == 2
    assert len(_rows(made.emails)) == 22


# ---------------------------------------------------------------------------
# the send
# ---------------------------------------------------------------------------

def test_the_drain_sends_it_and_marks_the_claim_sent(made, on, capsys):
    e = made(name='Tirzah')
    _run()
    smtp = _drain([e])
    assert [s['to_addr'] for s in smtp.sent] == [e]
    sent = smtp.sent[0]
    assert sent['subject'] == 'Your Ahavah sign-up is waiting' and sent['kind'] == 'unfinished_signup'
    assert sent['from_addr'] == us.FROM_ADDR and sent['bulk'] is True
    assert _rows([e])[0]['state'] == 'accepted'
    claim = _claim(e)
    assert claim['sent_at'] is not None and claim['message_id'] == 'mid-1'


def test_the_drain_refuses_it_once_an_account_is_made(made, on, make_person):
    e = made()
    _run()
    make_person(name='JoinedSince', email=e)
    assert _drain([e]).sent == []
    r = _rows([e])[0]
    assert (r['state'], r['last_error']) == ('skipped', 'member_now')
    assert _claim(e)['sent_at'] is None


def test_the_drain_refuses_it_once_the_switch_is_off(made, on, monkeypatch):
    e = made()
    _run()
    monkeypatch.setenv(SWITCH_ENV, '0')
    assert _drain([e]).sent == []
    assert _rows([e])[0]['last_error'] == 'switched_off'


def test_the_unsubscribe_link_works_with_no_account(made, on, client):
    e = made()
    _run()
    assert client.post(f"/u/{make_token('signup', e)}").status_code == 200
    assert _claim(e)['unsubscribed_at'] is not None
    assert _drain([e]).sent == []
    assert _rows([e])[0]['last_error'] == 'unsubscribed'
    # An address that never had the reminder: the page still says done.
    assert client.post(f"/u/{make_token('signup', 'nobody-' + uuid4().hex[:6] + '@ahavah-test.invalid')}"
                       ).status_code == 200


# ---------------------------------------------------------------------------
# the words and the logs
# ---------------------------------------------------------------------------

def test_the_email_carries_the_approved_words():
    subject, html = us.preview('owner@ahavah-test.invalid')
    assert subject == 'Your Ahavah sign-up is waiting'
    for words in ('A few steps left, then the community can see you.', 'Almost there',
                  'title-finish-profile.png', 'title-finish-profile-wht.png', 'Finish your profile.',
                  'You started joining Ahavah and stopped before the end. It takes a few minutes to finish, '
                  'and then the community can see your profile.',
                  'Finish signing up', 'It takes about 2 minutes.',
                  "You're receiving this because you started signing up for Ahavah.",
                  'Unsubscribe', 'Help', '/u/signup.'):
        assert words in html, words
    assert 'href="https://get.ahavah.app/"' in html
    assert '—' not in html and '&mdash;' not in html
    copy = (us.SUBJECT, us.PREHEADER, us.CHIP, *us.PARAGRAPHS, us.BUTTON, us.CALLOUT, us.FOOTER_REASON)
    assert not [c for c in copy if '!' in c or '—' in c or 'dating' in c.lower()]
    assert us.FROM_ADDR == 'support@ahavah.app'


def test_the_button_link_names_nobody(made, on):
    e = made(name='Tirzah')
    _run()
    html = _rows([e])[0]['html']
    assert 'Tirzah' not in html
    assert 'href="https://get.ahavah.app/"' in html


def test_the_logs_name_nobody(made, on, capsys):
    names = ['Tirzah', 'Keziah', 'Jemimah']
    emails = [made(name=n) for n in names]
    _run()
    _drain(emails)
    out = capsys.readouterr().out
    assert 'unfinished_signup: 3 due, 3 queued' in out
    for n in names:
        assert n not in out
    for e in emails:
        assert e not in out and e.split('@')[0] not in out
