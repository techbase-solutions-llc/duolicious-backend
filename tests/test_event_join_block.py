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
