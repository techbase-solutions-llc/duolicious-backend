"""Mail for a lead (TEC-1845).

A lead has no person row, so its mail rides the same outbox with lead_id in
place of person_id: queued once per run, drained by the one drain, refused
for a suppressed address. News mail goes only to a lead whose address is
confirmed and who ticked the box (or, for an alert, asked for it), and
stops once the lead has left it. A confirmation the visitor asked for still
goes. No member send log is written for a lead, since it is keyed on a
person.

Confirmation emails to strangers draw complaints, so a lead flow asks
mail_refusal first: the free defences sign-in codes already have.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import outbox
from service.leads import confirm_lead, mail_refusal, record_lead
from service.unsubscribe import make_token, stamp_unsubscribed

pytestmark = pytest.mark.usefixtures('growth_schema')

CAMPAIGN = 'test-lead-mail'


class _StubSmtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


@pytest.fixture
def lead():
    """A mailable lead (ahavah-test.invalid is not suppressed), deleted with
    its mail afterwards. `consent` ticks the news box; `confirmed` proves
    the address."""
    made: list[str] = []

    def _make(source: str = 'alert:visitor', *, consent: bool = False,
              confirmed: bool = False) -> tuple[int, str]:
        email = f'leadmail-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(email)
        with api_tx() as tx:
            lead_id = record_lead(tx, email=email, source=source, marketing_consent=consent,
                                  consent_wording='test-2026-11' if consent else None)
            if confirmed:
                confirm_lead(tx, lead_id, 'link')
        return lead_id, email

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _queue(lead_id, email, *, run='run-1', marketing=False, requested=False):
    with api_tx() as tx:
        return outbox.enqueue_for_lead(
            tx, campaign=CAMPAIGN, campaign_id=run, lead_id=lead_id, email=email,
            subject='Please confirm', html='<p>Confirm</p>', from_addr=None,
            marketing=marketing, requested=requested)


def _insert_news_row(lead_id: int, email: str, run: str) -> int:
    """A news row written straight to the outbox, past enqueue_for_lead's own
    check, so the drain's re-check is what decides."""
    payload = dict(subject='News', html='<p>News</p>', from_addr=None, list_unsubscribe=None,
                   post_send=None, cap_days=0, requires_spotlight_opt_in=False, requested=False)
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO email_outbox (campaign, campaign_id, lead_id, email, payload, exempt,
                                         unsub_scope)
               VALUES (%(c)s, %(r)s, %(l)s, %(e)s, %(p)s::jsonb, FALSE, 'news') RETURNING id""",
            dict(c=CAMPAIGN, r=run, l=lead_id, e=email, p=json.dumps(payload))).fetchone()['id']


def _drain_only(lead_id: int) -> list[dict]:
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND lead_id IS DISTINCT FROM %(l)s""",
                   dict(l=lead_id))
    smtp = _StubSmtp()
    outbox.drain(api_tx, smtp)
    return smtp.sent


def _state(row_id: int) -> tuple[str, str]:
    with api_tx('read committed') as tx:
        r = tx.execute('SELECT state, last_error FROM email_outbox WHERE id = %(i)s',
                       dict(i=row_id)).fetchone()
    return r['state'], r['last_error']


def test_lead_mail_is_queued_once_per_run(lead):
    lead_id, email = lead()
    assert _queue(lead_id, email) is not None
    assert _queue(lead_id, email) is None
    assert _queue(lead_id, email, run='run-2') is not None


def test_the_drain_sends_lead_mail_and_writes_no_member_send_log(lead):
    lead_id, email = lead()
    row_id = _queue(lead_id, email)
    sent = _drain_only(lead_id)
    assert [s['to_addr'] for s in sent] == [email]
    assert _state(row_id)[0] == 'accepted'
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM email_send_log WHERE campaign = %(c)s',
                       dict(c=CAMPAIGN)).fetchone()['n']
    assert n == 0


def test_news_to_a_lead_that_left_is_skipped_but_a_confirmation_still_goes(lead):
    lead_id, email = lead(consent=True, confirmed=True)
    news = _queue(lead_id, email, run='news-1', marketing=True)
    confirmation = _queue(lead_id, email, run='confirm-1')
    with api_tx() as tx:
        stamp_unsubscribed(tx, 'news', email)
    sent = _drain_only(lead_id)
    assert _state(news) == ('skipped', 'unsubscribed')
    assert _state(confirmation)[0] == 'accepted'
    assert len(sent) == 1


def test_news_to_a_lead_who_never_ticked_the_box_is_refused(lead):
    # Every tool player is such a lead: the tools have no news box.
    lead_id, email = lead('tool:game-me', confirmed=True)
    assert _queue(lead_id, email, run='news-1', marketing=True) is None
    row_id = _insert_news_row(lead_id, email, 'news-2')
    _drain_only(lead_id)
    assert _state(row_id) == ('skipped', 'no_consent')
    alert_id, alert_email = lead('alert:visitor', confirmed=True)
    asked = _queue(alert_id, alert_email, run='alert-1', marketing=True, requested=True)
    assert asked is not None, 'an alert the visitor asked for needs no news box'
    _drain_only(alert_id)
    assert _state(asked)[0] == 'accepted'


def test_news_to_a_ticked_but_unconfirmed_lead_is_refused(lead):
    # Anyone can type someone else's address into a form and tick the box.
    lead_id, email = lead(consent=True)
    assert _queue(lead_id, email, run='news-1', marketing=True) is None
    assert _queue(lead_id, email, run='alert-1', marketing=True, requested=True) is None
    row_id = _insert_news_row(lead_id, email, 'news-2')
    _drain_only(lead_id)
    assert _state(row_id) == ('skipped', 'unconfirmed')


def test_an_exempt_confirmation_to_an_unconfirmed_lead_still_goes(lead):
    lead_id, email = lead()
    row_id = _queue(lead_id, email, run='confirm-1')
    sent = _drain_only(lead_id)
    assert _state(row_id)[0] == 'accepted'
    assert [s['to_addr'] for s in sent] == [email]


def test_the_unsubscribe_link_reaches_every_row_of_the_address(client, lead):
    first_id, email = lead('alert:visitor')
    with api_tx() as tx:
        second_id = record_lead(tx, email=email, source='event:sukkot-2027')
    r = client.post(f"/u/{make_token('news', email)}")
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        stamped = tx.execute(
            'SELECT count(*) AS n FROM lead WHERE id = ANY(%(i)s) AND unsubscribed_at IS NOT NULL',
            dict(i=[first_id, second_id])).fetchone()['n']
    assert stamped == 2


def test_the_unsubscribe_link_reaches_the_address_however_it_was_typed(client):
    name = f'ann{uuid4().hex[:8]}'
    plain = f'{name}@gmail.com'
    variant = f'{name[:3]}.{name[3:]}+news@gmail.com'
    with api_tx() as tx:
        first_id = record_lead(tx, email=variant, source='alert:visitor')
        second_id = record_lead(tx, email=plain, source='event:sukkot-2027')
    try:
        assert client.post(f"/u/{make_token('news', variant)}").status_code == 200
        with api_tx('read committed') as tx:
            stamped = tx.execute(
                'SELECT count(*) AS n FROM lead WHERE id = ANY(%(i)s) AND unsubscribed_at IS NOT NULL',
                dict(i=[first_id, second_id])).fetchone()['n']
        assert stamped == 2
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE normalized_email = %(ne)s', dict(ne=plain))


def test_member_mail_still_writes_its_send_log(make_person):
    person = make_person(name='OutboxControl', email=f'oc-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        row_id = outbox.enqueue(
            tx, campaign=CAMPAIGN, campaign_id='member-1', person_id=person['id'],
            email=f'oc-control@ahavah-test.invalid', subject='s', html='<p>h</p>',
            from_addr=None, unsub_scope='campaigns', exempt=True)
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND id <> %(i)s""", dict(i=row_id))
    outbox.drain(api_tx, _StubSmtp())
    with api_tx('read committed') as tx:
        n = tx.execute("""SELECT count(*) AS n FROM email_send_log
                           WHERE person_id = %(p)s AND campaign = %(c)s""",
                       dict(p=person['id'], c=CAMPAIGN)).fetchone()['n']
    assert n == 1


def test_a_filled_hidden_field_is_refused(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1',
                        website='https://spam.example') == 'honeypot'


def test_a_forged_stamp_is_refused(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1',
                        stamp='123.abc') == 'stamp_forged'


def test_a_domain_that_takes_no_mail_is_refused(signup_env):
    signup_env.dns['nomail-lead.example'] = False
    assert mail_refusal(email=f'x{uuid4().hex[:6]}@nomail-lead.example',
                        ip='10.184.8.1') == 'no_mx'


def test_one_client_asking_too_often_is_refused(signup_env):
    # A public address, as tests/test_signup_new_address_limits.py uses:
    # private ones, and the documentation ranges Python counts as private,
    # are exempt from the limits.
    email = signup_env.new_email()
    answers = [mail_refusal(email=email, ip='45.33.10.8') for _ in range(6)]
    assert answers[:5] == [None] * 5
    assert answers[5] == 'ip_hour'


def test_a_plausible_request_is_let_through(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1') is None
