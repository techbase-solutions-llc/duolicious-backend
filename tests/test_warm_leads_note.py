"""The owner's personal note to the warm leads (health review, 13 Oct 2026,
finding 48).

A warm lead is an address on the waitlist or the beta list that never made
an account, is still subscribed, and is not a suppressed or sample address.
Each one gets the note once: a second `--send` emails nobody twice, and a
`--preview` proof records nothing against any lead.

No mail leaves the test: every send goes to a stub with the Smtp.send
signature, the way tests/conftest.py's outbox_drain does it.
"""
from __future__ import annotations

import email as email_lib
from pathlib import Path
from uuid import uuid4

import pytest

import smtp as smtp_module
from database import api_tx
from smtp import Smtp

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0063_lead_email_send.sql')


@pytest.fixture(scope='module', autouse=True)
def _schema():
    """The send log is new in 0063. The migration is idempotent, so applying
    it here is the same thing the deploy does."""
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


class _StubSmtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


@pytest.fixture
def leads():
    """Makes waitlist and beta rows on mailable addresses and deletes every
    trace of them afterwards. The suite shares one database."""
    made: list[str] = []

    def _new(prefix: str = 'lead') -> str:
        address = f'{prefix}-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(address)
        return address

    def _waitlist(address: str, answers: dict | None = None, unsubscribed: bool = False):
        import json
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO waitlist_signup (email, answers, unsubscribed_at)
                   VALUES (%(e)s, %(a)s::jsonb, CASE WHEN %(u)s THEN NOW() END)""",
                dict(e=address, a=json.dumps(answers or {}), u=unsubscribed))
        if address not in made:
            made.append(address)

    def _beta(address: str, unsubscribed: bool = False):
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO beta_signup (email, unsubscribed_at)
                   VALUES (%(e)s, CASE WHEN %(u)s THEN NOW() END)""",
                dict(e=address, u=unsubscribed))
        if address not in made:
            made.append(address)

    class _Leads:
        new = staticmethod(_new)
        waitlist = staticmethod(_waitlist)
        beta = staticmethod(_beta)

    yield _Leads

    with api_tx() as tx:
        for address in made:
            tx.execute('DELETE FROM waitlist_signup WHERE email = %(e)s', dict(e=address))
            tx.execute('DELETE FROM beta_signup WHERE email = %(e)s', dict(e=address))
            tx.execute('DELETE FROM lead_email_send WHERE email = %(e)s', dict(e=address))


def _eligible() -> dict[str, dict]:
    from emails.send_warm_leads_note import eligible_leads
    with api_tx() as tx:
        return {row['email']: row for row in eligible_leads(tx)}


def _logged(addresses) -> int:
    from emails.send_warm_leads_note import CAMPAIGN
    with api_tx() as tx:
        return tx.execute(
            """SELECT count(*) AS n FROM lead_email_send
                WHERE campaign = %(c)s AND email = ANY(%(e)s)""",
            dict(c=CAMPAIGN, e=list(addresses))).fetchone()['n']


# --- who gets the note -----------------------------------------------------

def test_a_waitlist_lead_and_a_beta_lead_with_no_account_are_recipients(leads):
    on_waitlist, on_beta = leads.new('wl'), leads.new('beta')
    leads.waitlist(on_waitlist)
    leads.beta(on_beta)
    got = _eligible()
    assert got[on_waitlist]['scope'] == 'waitlist'
    assert got[on_beta]['scope'] == 'beta'


def test_a_lead_who_made_an_account_is_not(leads, make_person):
    address = leads.new('member')
    leads.waitlist(address)
    make_person(name='Joined', email=address)
    assert address not in _eligible()


def test_an_account_is_matched_case_blind_and_on_the_normalised_address(leads, make_person):
    """The lead tables store the address lower-cased; an account may have
    typed it with capitals, or as a Gmail dot variant that only the
    normalised address shares."""
    capitals = leads.new('caps')
    leads.beta(capitals)
    make_person(name='Caps', email=capitals.upper())

    dotted_lead = f'warm.{uuid4().hex[:8]}@gmail.com'
    leads.waitlist(dotted_lead)
    person = make_person(name='Dots', email=dotted_lead.replace('.', '', 1))
    with api_tx() as tx:
        tx.execute('UPDATE person SET normalized_email = %(n)s WHERE id = %(i)s',
                   dict(n=dotted_lead.replace('.', '', 1), i=person['id']))

    got = _eligible()
    assert capitals not in got
    assert dotted_lead not in got


def test_an_unsubscribe_in_either_table_excludes_the_lead(leads):
    gone_waitlist, gone_beta = leads.new('unsub-wl'), leads.new('unsub-beta')
    leads.waitlist(gone_waitlist, unsubscribed=True)
    leads.beta(gone_waitlist)
    leads.waitlist(gone_beta)
    leads.beta(gone_beta, unsubscribed=True)
    got = _eligible()
    assert gone_waitlist not in got
    assert gone_beta not in got


def test_suppressed_and_sample_addresses_are_not_recipients(leads):
    sample = f'sample-{uuid4().hex[:8]}@example.com'
    staff = f'staff-{uuid4().hex[:8]}@techbaseltd.com'
    leads.waitlist(sample)
    leads.beta(staff)
    got = _eligible()
    assert sample not in got
    assert staff not in got


def test_a_lead_on_both_lists_appears_once_with_the_waitlist_link(leads):
    both = leads.new('both')
    leads.waitlist(both, answers={'country': 'US'})
    leads.beta(both)
    from emails.send_warm_leads_note import eligible_leads
    with api_tx() as tx:
        rows = [r for r in eligible_leads(tx) if r['email'] == both]
    assert len(rows) == 1
    assert rows[0]['scope'] == 'waitlist'


# --- the greeting ----------------------------------------------------------

@pytest.mark.parametrize('answers, expected', [
    ({'first_name': '  miriam '}, 'Miriam'),
    ({'firstName': 'Ruth'}, 'Ruth'),
    ({'name': 'David Levi'}, 'David'),
    ({'country': 'US', 'sex': 'female'}, None),
    ({'name': '   '}, None),
    ({}, None),
    (None, None),
])
def test_first_name_comes_from_the_stored_answers_or_not_at_all(answers, expected):
    from emails.send_warm_leads_note import first_name
    assert first_name(answers) == expected


def test_a_stored_name_reaches_the_lead_row(leads):
    named = leads.new('named')
    leads.waitlist(named, answers={'first_name': 'Hannah'})
    assert _eligible()[named]['first_name'] == 'Hannah'


def test_the_greeting_falls_back_to_shalom_with_no_name():
    from emails.warm_leads_note import note_html, note_text
    html = note_html(None, 58, 'https://ahavah.app/u/tok')
    text = note_text(None, 58, 'https://ahavah.app/u/tok')
    assert 'Shalom,' in html and 'Shalom,' in text
    assert 'Shalom ,' not in html and 'Shalom ,' not in text
    named = note_html('Hannah', 58, 'https://ahavah.app/u/tok')
    assert 'Shalom Hannah,' in named


def test_a_name_is_escaped_in_the_html():
    from emails.warm_leads_note import note_html
    html = note_html('<b>Eve</b>', 58, 'https://ahavah.app/u/tok')
    assert '<b>Eve</b>' not in html
    assert '&lt;b&gt;Eve&lt;/b&gt;' in html


# --- the note itself -------------------------------------------------------

def test_the_note_carries_the_approved_wording():
    from emails.warm_leads_note import SUBJECT, note_html, note_text
    assert SUBJECT == 'A quick question from Ehud'
    for body in (note_html('Ruth', 58, 'https://x/u/t'), note_text('Ruth', 58, 'https://x/u/t')):
        assert ('You put your name down for Ahavah earlier this year. The app has been '
                'open for a few months now, and 58 believers have joined, most of them '
                'in the United States.') in ' '.join(body.split())
        assert ('I noticed you never made a profile, and I would like to know why. Was it '
                'the timing, something on the sign-up screens, or did Ahavah not look like '
                'what you were hoping for? A one-line reply is plenty, and I read every '
                'one.') in ' '.join(body.split())
        assert 'Ehud' in body
        assert '\u2014' not in body, 'no em dash in the note'


def test_the_note_is_plain_with_no_image_and_no_button():
    from emails.warm_leads_note import note_html
    html = note_html('Ruth', 58, 'https://x/u/t')
    assert '<img' not in html
    assert '<table' not in html
    assert 'href="https://ahavah.app"' in html
    assert '>ahavah.app</a>' in html


def test_the_unsubscribe_link_is_in_both_parts():
    from emails.warm_leads_note import note_html, note_text
    url = 'https://ahavah.app/u/waitlist.abc.def'
    assert f'href="{url}"' in note_html(None, 58, url)
    assert url in note_text(None, 58, url)


def test_a_lead_message_has_a_working_unsubscribe_link_and_header(leads):
    from emails.send_warm_leads_note import build_message
    from service.unsubscribe import parse_token
    address = leads.new('unsub-link')
    msg = build_message(address, 'Ruth', 58, 'beta')
    token = msg['unsubscribe_url'].rsplit('/u/', 1)[1]
    assert parse_token(token) == ('beta', address)
    assert msg['unsubscribe_url'] in msg['html']
    assert msg['unsubscribe_url'] in msg['text']
    assert f"<{msg['unsubscribe_url']}>" in msg['list_unsubscribe']
    assert 'mailto:' in msg['list_unsubscribe']


def test_the_unsubscribe_link_stops_the_next_send(leads, client):
    from emails.send_warm_leads_note import build_message
    address = leads.new('unsub-click')
    leads.waitlist(address)
    msg = build_message(address, None, 58, 'waitlist')
    path = msg['unsubscribe_url'].split('://', 1)[1].split('/', 1)[1]
    assert client.post('/' + path).status_code == 200
    assert address not in _eligible()


# --- N ---------------------------------------------------------------------

def test_n_counts_activated_members_and_never_staff(make_person):
    from emails.send_warm_leads_note import member_count
    with api_tx() as tx:
        before = member_count(tx)
    make_person(name='Member')
    staff = make_person(name='Staff')
    resting = make_person(name='Resting')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin'] WHERE id = %(i)s", dict(i=staff['id']))
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=resting['id']))
        assert member_count(tx) == before + 1


# --- preview ---------------------------------------------------------------

def test_a_preview_sends_one_proof_and_records_nothing(leads):
    from emails.send_warm_leads_note import FROM_ADDR, FROM_NAME, SAMPLE_FIRST_NAME, send_preview
    proof_to = leads.new('proof')
    leads.waitlist(proof_to)
    smtp = _StubSmtp()
    send_preview(smtp, proof_to, 58, reply_to='owner@ahavah-test.invalid')
    assert len(smtp.sent) == 1
    sent = smtp.sent[0]
    assert sent['to_addr'] == proof_to
    assert sent['subject'] == 'A quick question from Ehud'
    assert f'Shalom {SAMPLE_FIRST_NAME},' in sent['body']
    assert sent['from_addr'] == FROM_ADDR == 'support@ahavah.app'
    assert sent['from_name'] == FROM_NAME == 'Ehud at Ahavah'
    assert sent['reply_to'] == 'owner@ahavah-test.invalid'
    assert sent['text_body'] and sent['list_unsubscribe']
    assert _logged([proof_to]) == 0
    assert proof_to in _eligible(), 'a proof must not use up the lead'


def test_a_preview_reaches_a_staff_inbox_the_bulk_send_would_skip():
    """The proof goes where the operator points it, and that is usually a
    techbaseltd.com inbox, which the bulk send suppresses."""
    from emails.send_warm_leads_note import send_preview
    smtp = _StubSmtp()
    send_preview(smtp, 'admin@techbaseltd.com', 58, reply_to='support@ahavah.app')
    assert [s['to_addr'] for s in smtp.sent] == ['admin@techbaseltd.com']


# --- send ------------------------------------------------------------------

def _mine(addresses):
    wanted = set(addresses)
    from emails.send_warm_leads_note import eligible_leads
    with api_tx() as tx:
        return [r for r in eligible_leads(tx) if r['email'] in wanted]


def test_send_mails_each_lead_once_and_a_second_send_mails_nobody(leads):
    from emails.send_warm_leads_note import send_all
    one, two = leads.new('send-a'), leads.new('send-b')
    leads.waitlist(one, answers={'first_name': 'Leah'})
    leads.waitlist(two)
    leads.beta(two)

    smtp = _StubSmtp()
    first = send_all(api_tx, smtp, _mine([one, two]), 58,
                     reply_to='support@ahavah.app', pause=0)
    assert sorted(s['to_addr'] for s in smtp.sent) == sorted([one, two])
    assert first['sent'] == 2
    assert _logged([one, two]) == 2
    by_to = {s['to_addr']: s for s in smtp.sent}
    assert 'Shalom Leah,' in by_to[one]['body']
    assert 'Shalom,' in by_to[two]['body']
    assert '58 believers' in by_to[one]['body']

    again = _StubSmtp()
    second = send_all(api_tx, again, _mine([one, two]), 58,
                      reply_to='support@ahavah.app', pause=0)
    assert again.sent == []
    assert second['sent'] == 0
    assert second['already_sent'] == 2


def test_a_send_stamps_the_lead_before_it_mails(leads):
    """The claim is committed before the mailer is called, so a crash part
    way through cannot lead to a second email on the re-run."""
    from emails.send_warm_leads_note import send_all
    address = leads.new('claim')
    leads.beta(address)
    seen_at_send: list[int] = []

    class _Checking(_StubSmtp):
        def send(self, **kw):
            seen_at_send.append(_logged([kw['to_addr']]))
            return super().send(**kw)

    send_all(api_tx, _Checking(), _mine([address]), 58, reply_to='support@ahavah.app', pause=0)
    assert seen_at_send == [1]


def test_a_send_with_no_message_id_is_kept_claimed_and_reported(leads):
    from emails.send_warm_leads_note import send_all
    address = leads.new('no-id')
    leads.waitlist(address)

    class _NoId(_StubSmtp):
        def send(self, **kw):
            super().send(**kw)
            return None

    result = send_all(api_tx, _NoId(), _mine([address]), 58,
                      reply_to='support@ahavah.app', pause=0)
    assert result['unconfirmed'] == 1
    again = _StubSmtp()
    send_all(api_tx, again, _mine([address]), 58, reply_to='support@ahavah.app', pause=0)
    assert again.sent == [], 'an unconfirmed send must not be repeated automatically'


def test_send_records_the_message_id(leads):
    from emails.send_warm_leads_note import CAMPAIGN, send_all
    address = leads.new('mid')
    leads.waitlist(address)
    send_all(api_tx, _StubSmtp(), _mine([address]), 58, reply_to='support@ahavah.app', pause=0)
    with api_tx() as tx:
        row = tx.execute(
            'SELECT message_id, sent_at FROM lead_email_send WHERE email = %(e)s AND campaign = %(c)s',
            dict(e=address, c=CAMPAIGN)).fetchone()
    assert row['message_id'] == 'mid-1'
    assert row['sent_at'] is not None


def test_send_never_mails_a_suppressed_address_even_if_handed_one():
    from emails.send_warm_leads_note import send_all
    smtp = _StubSmtp()
    rows = [dict(email='admin@techbaseltd.com', first_name=None, scope='beta')]
    result = send_all(api_tx, smtp, rows, 58, reply_to='support@ahavah.app', pause=0)
    assert smtp.sent == []
    assert result['skipped_suppressed'] == 1


# --- the command line ------------------------------------------------------

def test_a_dry_run_prints_counts_and_never_an_address(leads, capsys, monkeypatch):
    import emails.send_warm_leads_note as mod
    address = leads.new('dry')
    leads.waitlist(address)

    def _no_mail(*a, **kw):
        raise AssertionError('a dry run must not reach the mailer')

    monkeypatch.setattr(mod, '_mailer', _no_mail)
    mod.main([])
    out = capsys.readouterr().out
    assert '@' not in out.replace('support@ahavah.app', '')
    assert 'DRY RUN' in out
    assert 'N =' in out
    assert _logged([address]) == 0


# --- the mailer: display name and a text part ------------------------------

class _FakeResponse:
    status_code = 200
    text = ''

    def json(self):
        return {'id': 'msg-1'}


def test_the_resend_payload_carries_the_display_name_and_the_text_part(monkeypatch):
    monkeypatch.setattr(smtp_module, 'USE_RESEND_API', True)
    monkeypatch.setattr(smtp_module, 'RESEND_FROM_OVERRIDE', '')
    posted: dict = {}
    import requests

    def fake_post(url, json=None, headers=None, timeout=None):
        posted['json'] = json
        return _FakeResponse()

    monkeypatch.setattr(requests, 'post', fake_post)
    Smtp('h', 25, 'u', 're_key')._try_send(
        subject='s', body='<p>hi</p>', to_addr='to@example.com',
        from_addr='support@ahavah.app', from_name='Ehud at Ahavah', text_body='hi')
    assert posted['json']['from'] == 'Ehud at Ahavah <support@ahavah.app>'
    assert posted['json']['text'] == 'hi'


def test_the_resend_payload_is_unchanged_without_the_new_arguments(monkeypatch):
    monkeypatch.setattr(smtp_module, 'USE_RESEND_API', True)
    monkeypatch.setattr(smtp_module, 'RESEND_FROM_OVERRIDE', '')
    posted: dict = {}
    import requests

    def fake_post(url, json=None, headers=None, timeout=None):
        posted['json'] = json
        return _FakeResponse()

    monkeypatch.setattr(requests, 'post', fake_post)
    Smtp('h', 25, 'u', 're_key')._try_send(
        subject='s', body='<p>hi</p>', to_addr='to@example.com', from_addr='support@ahavah.app')
    assert set(posted['json']) == {'from', 'to', 'subject', 'html'}
    assert posted['json']['from'] == f'{smtp_module.PRODUCT_NAME} <support@ahavah.app>'


def test_the_smtp_message_has_a_plain_part_before_the_html_and_the_display_name(monkeypatch):
    monkeypatch.setattr(smtp_module, 'USE_RESEND_API', False)
    sent: list[str] = []

    class _Socket:
        def sendmail(self, *, from_addr, to_addrs, msg):
            sent.append(msg)

        def quit(self):
            pass

    mailer = Smtp('h', 25, 'u', 'p')
    mailer._smtp = _Socket()
    mailer._try_send(subject='s', body='<p>hi</p>', to_addr='to@example.com',
                     from_addr='support@ahavah.app', from_name='Ehud at Ahavah',
                     text_body='hi there')
    msg = email_lib.message_from_string(sent[0])
    assert msg['From'] == 'Ehud at Ahavah <support@ahavah.app>'
    parts = [p.get_content_type() for p in msg.walk() if not p.is_multipart()]
    assert parts == ['text/plain', 'text/html']
