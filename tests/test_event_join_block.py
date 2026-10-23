"""The "Join Ahavah" block for gathering guests who are not members
(TEC-1845, docs/superpowers/plans/2026-10-22-events-invite-to-join.md,
Tasks 5 and 6): the join link, who is offered it on the confirmed page
(rsvp.join_offer), and the block in the confirm and reminder emails.
Members never; nor an address that left the news mail (Owner decision 7).
AHAVAH_EVENTS_JOIN_BLOCK_ENABLED is set here, not by events_live."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')
BLOCK_ENV = 'AHAVAH_EVENTS_JOIN_BLOCK_ENABLED'


@pytest.fixture
def block_on(monkeypatch):
    monkeypatch.setenv(BLOCK_ENV, '1')


def _view(client, token: str) -> dict:
    r = client.get(f'/rsvp/{token}')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _address() -> str:
    return f'join-block-{uuid4().hex[:10]}@ahavah-test.invalid'


def test_the_link_carries_the_gathering():
    from service.events.join import join_url
    url = join_url('marriage-evening-a1b2c3')
    assert url.endswith('/auth/sign-up?src=event%3Amarriage-evening-a1b2c3')
    with pytest.raises(ValueError):
        join_url('<script>')


def test_off_by_default_the_view_offers_nothing(client, published, confirmed_guest, monkeypatch):
    monkeypatch.delenv(BLOCK_ENV, raising=False)
    g = confirmed_guest(published())
    assert _view(client, g['token'])['rsvp']['join_offer'] is False


def test_the_block_needs_events_live(client, published, confirmed_guest, block_on, monkeypatch):
    g = confirmed_guest(published())
    from service.events import join
    with api_tx() as tx:
        r = dict(tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s', dict(i=g['id'])).fetchone())
        assert join.offers_join(tx, r) is True
        monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
        assert join.offers_join(tx, r) is False


def test_a_confirmed_guest_who_is_not_a_member_is_offered(client, published, confirmed_guest, block_on):
    g = confirmed_guest(published())
    view = _view(client, g['token'])
    assert view['rsvp']['join_offer'] is True
    assert 'sign-up' not in str(view)  # the page builds the link from event.slug


def test_a_member_is_never_offered(client, published, confirmed_guest, make_person, block_on):
    slug = published()
    address = _address()
    p = make_person(name='JoinBlockMember', email=address)
    by_account = confirmed_guest(slug, person_id=p['id'], email=address)
    assert _view(client, by_account['token'])['rsvp']['join_offer'] is False
    other = published()
    by_address = confirmed_guest(other, email=address)
    assert _view(client, by_address['token'])['rsvp']['join_offer'] is False


def test_no_offer_once_the_address_has_joined(client, published, confirmed_guest, make_person, block_on):
    address = _address()
    g = confirmed_guest(published(), email=address)
    assert _view(client, g['token'])['rsvp']['join_offer'] is True
    make_person(name='JoinedSince', email=address)
    assert _view(client, g['token'])['rsvp']['join_offer'] is False


def test_no_offer_to_an_address_that_left_the_news(client, published, confirmed_guest, block_on):
    g = confirmed_guest(published())
    with api_tx() as tx:
        tx.execute("""UPDATE lead SET unsubscribed_at = NOW()
                       WHERE id = (SELECT lead_id FROM event_rsvp WHERE id = %(i)s)""", dict(i=g['id']))
    assert _view(client, g['token'])['rsvp']['join_offer'] is False


def test_no_offer_before_confirming_or_after_cancelling(client, published, confirmed_guest, block_on):
    slug = published()
    waiting, cancelled = confirmed_guest(slug), confirmed_guest(slug)
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET confirmed_at = NULL WHERE id = %(i)s', dict(i=waiting['id']))
        tx.execute("UPDATE event_rsvp SET status = 'cancelled' WHERE id = %(i)s", dict(i=cancelled['id']))
    assert _view(client, waiting['token'])['rsvp']['join_offer'] is False
    assert _view(client, cancelled['token'])['rsvp']['join_offer'] is False


def test_mail_block_allowed_follows_the_rest_days(monkeypatch):
    from datetime import date, datetime, timezone
    import service.spotlight.restdays as rd
    from service.events.join import mail_block_allowed
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2026, 11, 9))
    monkeypatch.setattr(rd, 'REST_DAYS', (date(2026, 11, 7),))
    assert mail_block_allowed(datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc))
    # 17:00 Barbados (21:00 UTC) the evening before: inside the rest period.
    assert not mail_block_allowed(datetime(2026, 11, 6, 21, 30, tzinfo=timezone.utc))
    assert not mail_block_allowed(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Task 6: the block in the confirm and reminder emails
# ---------------------------------------------------------------------------

def _rows_for(campaign, slug):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT o.* FROM email_outbox o JOIN event_rsvp r
                   ON r.id = split_part(o.campaign_id, ':', 1)::bigint
                 JOIN event e ON e.id = r.event_id
                WHERE o.campaign = %(c)s AND e.slug = %(s)s ORDER BY o.id""",
            dict(c=campaign, s=slug)).fetchall()]


def _rsvp_post(client, slug, email, headers=None):
    r = client.post(f'/events/{slug}/rsvp', headers=headers or {},
                    json=dict(name='Hannah Okafor', email=email, party_size=1))
    assert r.status_code in (200, 201), r.get_data(as_text=True)


def _reminder(g):
    from service.events import mail, rsvp
    with api_tx() as tx:
        token = rsvp.reissue_token(tx, g['id'])
        return mail.queue_reminder(tx, g['id'], token)


def _sign_up(slug):
    return f'/auth/sign-up?src=event%3A{slug}'


def test_off_the_confirm_and_reminder_are_unchanged(client, published, confirmed_guest, mail_allowed,
                                                    monkeypatch):
    monkeypatch.delenv(BLOCK_ENV, raising=False)
    slug = published()
    _rsvp_post(client, slug, _address())
    _reminder(confirmed_guest(slug))
    for campaign in ('event_confirm', 'event_reminder'):
        [row] = _rows_for(campaign, slug)
        assert '/auth/sign-up' not in row['payload']['html']


def test_the_builders_are_unchanged_without_a_link():
    from service.events import mail
    v = mail.sample_view()
    assert mail.confirm_email(v, 't' * 32) == mail.confirm_email(v, 't' * 32, join_url=None)
    assert '/auth/sign-up' not in mail.confirm_email(v, 't' * 32)[1]


def test_on_a_visitors_confirm_email_carries_the_block_below_the_button(client, published, block_on,
                                                                        mail_allowed):
    slug = published()
    _rsvp_post(client, slug, _address())
    [row] = _rows_for('event_confirm', slug)
    html = row['payload']['html']
    assert html.count(_sign_up(slug)) == 1
    # The share line is the preheader too, so its last place is the body's.
    assert html.index('Confirm my place') < html.rindex('We share the address once you confirm.') \
        < html.index(_sign_up(slug))
    assert 'Ahavah is matchmaking for Torah-observant believers who hope to marry.' in html
    assert html.count('Confirm my place') == 1 and html.count('padding:18px 32px') == 1  # one button


def test_on_the_reminder_carries_it_for_a_visitor(published, confirmed_guest, block_on):
    from service.events import mail
    slug = published()
    assert _reminder(confirmed_guest(slug)) is not None
    [row] = _rows_for('event_reminder', slug)
    html = row['payload']['html']
    assert html.index('Cancel my place') < html.index(mail.SAFETY) < html.index(_sign_up(slug))


def test_a_member_guest_gets_no_block(client, published, confirmed_guest, make_person, block_on,
                                      mail_allowed):
    slug = published()
    address = _address()
    p = make_person(name='JoinBlockMember', email=address)
    _rsvp_post(client, slug, address)
    [confirm] = _rows_for('event_confirm', slug)
    assert confirm['person_id'] == p['id'] and '/auth/sign-up' not in confirm['payload']['html']
    other = published()
    _reminder(confirmed_guest(other, person_id=p['id'], email=address))
    [reminder] = _rows_for('event_reminder', other)
    assert '/auth/sign-up' not in reminder['payload']['html']


def test_no_block_once_the_address_has_joined(published, confirmed_guest, make_person, block_on, monkeypatch):
    """A guest who joined between the RSVP and the reminder: the reminder
    job builds it without the block (Review focus 1)."""
    from datetime import datetime, timedelta, timezone
    from service.events import jobs
    now = datetime.now(timezone.utc)
    slug = published(starts_at=now + timedelta(hours=30), tz='UTC', tz_label='UTC')
    address = _address()
    confirmed_guest(slug, email=address)
    make_person(name='JoinedBeforeReminder', email=address)
    day_before = (now + timedelta(hours=30)).date() - timedelta(days=1)
    tick = datetime.combine(day_before, datetime.min.time(), timezone.utc) + timedelta(hours=12)
    with api_tx() as tx:
        jobs.queue_reminders(tx, tick)
    rows = _rows_for('event_reminder', slug)
    assert len(rows) == 1 and '/auth/sign-up' not in rows[0]['payload']['html']


def test_no_block_inside_a_rest_period_or_beyond_the_calendar(client, published, block_on, mail_allowed,
                                                              monkeypatch):
    from datetime import date, datetime, timedelta, timezone
    import service.spotlight.restdays as rd
    from service.spotlight.restdays import BARBADOS
    today = datetime.now(timezone.utc).astimezone(BARBADOS).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (today, today + timedelta(days=1)))
    inside = published()
    _rsvp_post(client, inside, _address())
    [row] = _rows_for('event_confirm', inside)
    assert '/auth/sign-up' not in row['payload']['html']
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', today - timedelta(days=1))
    beyond = published()
    _rsvp_post(client, beyond, _address())
    [row] = _rows_for('event_confirm', beyond)
    assert 'Confirm my place' in row['payload']['html'] and '/auth/sign-up' not in row['payload']['html']


def test_the_block_carries_no_venue_and_escapes_the_title():
    from service.events import mail
    from service.events.join import join_url
    block = mail.join_block(join_url('marriage-evening-a1b2c3'))
    assert 'Elm Street' not in block and 'meet.example.com' not in block
    assert 'src=event%3Amarriage-evening-a1b2c3' in block
    assert '<h1' not in block and '<h2' not in block
    view = mail.sample_view(title='<b>x</b> & "y"', confirmed=True)
    _, html_ = mail.reminder_email(view, 't' * 32, join_url=join_url('marriage-evening-a1b2c3'))
    assert '<b>x</b>' not in html_ and '&lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;' in html_
    assert html_.count('src=event%3Amarriage-evening-a1b2c3') == 1


def test_the_join_previews_carry_the_block():
    from service.events import mail
    for fn in (mail.preview_confirm_join, mail.preview_confirm_online_join,
               mail.preview_reminder_join, mail.preview_reminder_online_join):
        subject, html_ = fn('proof@ahavah-test.invalid')
        assert subject and '/auth/sign-up?src=event%3A' in html_


# ---------------------------------------------------------------------------
# Review fixes (23 Oct 2026): leaving the news is read for the address, and
# the block is checked again when the email is sent.
# ---------------------------------------------------------------------------

def test_no_offer_to_an_address_that_left_the_news_at_another_gathering(client, published, confirmed_guest,
                                                                         block_on):
    """The news unsubscribe stamps the rows the address has at that moment.
    A later gathering's RSVP makes a fresh event:{slug} row without the
    stamp; the address has still left the news (Owner decision 7)."""
    from service.unsubscribe import stamp_unsubscribed
    address = _address()
    confirmed_guest(published(), email=address)
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'news', address)
    later = confirmed_guest(published(), email=address)
    with api_tx('read committed') as tx:
        assert tx.execute("""SELECT l.unsubscribed_at FROM lead l JOIN event_rsvp r ON r.lead_id = l.id
                              WHERE r.id = %(i)s""", dict(i=later['id'])).fetchone()['unsubscribed_at'] is None
    assert _view(client, later['token'])['rsvp']['join_offer'] is False


def _drain_only(row_id):
    """Send this one row through the outbox, every other due row parked."""
    from service.campaigns import outbox

    class _Smtp:
        def __init__(self):
            self.sent: list = []

        def send(self, **kw):
            self.sent.append(kw)
            return 'mid'
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND id <> %(i)s""", dict(i=row_id))
    smtp = _Smtp()
    outbox.drain(api_tx, smtp, limit=5)
    with api_tx('read committed') as tx:
        state = tx.execute('SELECT state FROM email_outbox WHERE id = %(i)s', dict(i=row_id)).fetchone()['state']
    return state, smtp.sent


def test_the_block_goes_with_the_email_for_a_guest(published, confirmed_guest, block_on):
    slug = published()
    row_id = _reminder(confirmed_guest(slug, email=_address()))
    state, sent = _drain_only(row_id)
    assert state == 'accepted' and _sign_up(slug) in sent[0]['body']


def test_the_block_is_left_out_at_send_time_once_the_address_has_joined(published, confirmed_guest,
                                                                       make_person, block_on):
    """Review focus 1 at the send: the reminder was queued with the block,
    the guest finished onboarding before the drain sent it. The reminder
    still goes, without the block."""
    slug = published()
    address = _address()
    row_id = _reminder(confirmed_guest(slug, email=address))
    with api_tx('read committed') as tx:
        assert _sign_up(slug) in tx.execute('SELECT payload FROM email_outbox WHERE id = %(i)s',
                                            dict(i=row_id)).fetchone()['payload']['html']
    make_person(name='JoinedBeforeTheSend', email=address)
    state, sent = _drain_only(row_id)
    assert state == 'accepted'
    body = sent[0]['body']
    assert 'Cancel my place' in body and '/auth/sign-up' not in body
    assert 'Ahavah is matchmaking for Torah-observant believers who hope to marry.' not in body


def test_the_block_is_left_out_at_send_time_once_the_address_has_left_the_news(client, published, block_on,
                                                                              mail_allowed):
    from service.unsubscribe import stamp_unsubscribed
    slug = published()
    address = _address()
    _rsvp_post(client, slug, address)
    [row] = _rows_for('event_confirm', slug)
    assert _sign_up(slug) in row['payload']['html']
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'news', address)
    state, sent = _drain_only(row['id'])
    assert state == 'accepted'
    assert 'Confirm my place' in sent[0]['body'] and '/auth/sign-up' not in sent[0]['body']
