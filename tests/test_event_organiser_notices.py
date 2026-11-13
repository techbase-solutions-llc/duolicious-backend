"""The organiser hears what changes their guest list (TEC-2077).

Labs F34: a guest who cancels a confirmed place reads "The organiser has
been told.", so the organiser is emailed (event_place_cancelled, on the
digest's switch). Labs F33: a gathering the organiser publishes themselves
sends them the "is live" email, as an admin's approval does.
"""
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')


def _rows(campaign, organiser_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM email_outbox WHERE campaign = %(c)s AND organiser_id = %(o)s ORDER BY id',
            dict(c=campaign, o=organiser_id)).fetchall()]


def test_a_guest_who_cancels_a_confirmed_place_tells_the_organiser(client, organiser, published,
                                                                   confirmed_guest):
    o = organiser()
    slug = published(organiser_row=o)
    g = confirmed_guest(slug, name='Hannah Okafor', party_size=2, share=True,
                        email='hannah-c@ahavah-test.invalid')
    confirmed_guest(slug, name='Lydia Cruz', party_size=3)
    assert client.post(f"/rsvp/{g['token']}/cancel").status_code == 200
    [row] = _rows('event_place_cancelled', o['id'])
    html = row['payload']['html']
    assert row['payload']['subject'] == 'Hannah Okafor cancelled their place at Marriage preparation evening'
    assert 'Hannah Okafor' in html and '2 people' in html and '<b>3 going</b> in total now.' in html
    assert 'hannah-c@' not in html and '/host/gatherings?t=' in html
    assert row['exempt'] is True and row['person_id'] is None and row['lead_id'] is None
    # Cancelling again tells nobody again.
    assert client.post(f"/rsvp/{g['token']}/cancel").status_code == 200
    assert len(_rows('event_place_cancelled', o['id'])) == 1


def test_an_unconfirmed_place_tells_nobody(client, organiser, published):
    o = organiser()
    slug = published(organiser_row=o)
    client.post(f'/events/{slug}/rsvp', json=dict(name='Unconfirmed', email='unc@ahavah-test.invalid',
                                                  party_size=1))
    with api_tx() as tx:
        rid = tx.execute("""SELECT r.id FROM event_rsvp r JOIN event e ON e.id = r.event_id
                             WHERE e.slug = %(s)s""", dict(s=slug)).fetchone()['id']
        from service.events import rsvp
        token = rsvp.reissue_token(tx, rid)
        rsvp.cancel(tx, token)
    assert _rows('event_place_cancelled', o['id']) == []


def test_the_digest_switch_turns_it_off(client, organiser, published, confirmed_guest, monkeypatch):
    o = organiser()
    slug = published(organiser_row=o)
    g = confirmed_guest(slug)
    monkeypatch.delenv('AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED')
    client.post(f"/rsvp/{g['token']}/cancel")
    assert _rows('event_place_cancelled', o['id']) == []


def test_nothing_for_a_gathering_that_ended_or_was_cancelled(organiser, published, confirmed_guest):
    from service.events import mail, rsvp
    o = organiser()
    past = published(organiser_row=o, starts_at=datetime.now(timezone.utc) - timedelta(days=2),
                     ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    off = published(organiser_row=o, status='cancelled')
    for slug in (past, off):
        g = confirmed_guest(slug)
        with api_tx() as tx:
            # The guest's link no longer opens such a gathering, so the
            # place is cancelled the way every cancel ends.
            row = dict(tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s', dict(i=g['id'])).fetchone())
            rsvp._cancel_row(tx, row)
    assert _rows('event_place_cancelled', o['id']) == []
    # The builder alone, for the escaping.
    evil = '<script>x</script>'
    _, html = mail.place_cancelled_email(dict(title=evil), dict(name=evil, party_size=1), 0, 'tok')
    assert '<script>' not in html


def test_a_member_cancelling_from_the_app_tells_the_organiser(organiser, published, confirmed_guest,
                                                              make_person):
    from service.events import rsvp
    o = organiser()
    slug = published(organiser_row=o)
    p = make_person(name='NoticeMember')
    g = confirmed_guest(slug, name='Notice Member', person_id=p['id'])
    with api_tx() as tx:
        rsvp.member_cancel(tx, p['id'], g['id'])
    [row] = _rows('event_place_cancelled', o['id'])
    assert 'Notice Member' in row['payload']['html']


def test_publishing_your_own_gathering_sends_the_live_email(client, organiser, event_cleanup):
    from tests.test_event_manage import draft
    o = organiser()
    slug = client.post('/organiser/events', headers=o['headers'], json=draft()).get_json()['slug']
    event_cleanup(slug)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == \
        {'status': 'published'}
    [row] = _rows('event_organiser_note', o['id'])
    assert row['payload']['subject'].endswith('is live on Ahavah')


def test_a_publish_that_waits_for_approval_sends_nothing(client, organiser, event_cleanup):
    from tests.test_event_manage import draft
    o = organiser(approved=False)
    slug = client.post('/organiser/events', headers=o['headers'], json=draft()).get_json()['slug']
    event_cleanup(slug)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == \
        {'status': 'pending'}
    assert _rows('event_organiser_note', o['id']) == []


def test_each_cancellation_of_a_booking_made_again_is_told(organiser, published, confirmed_guest,
                                                          make_person):
    """A member who books again from the app keeps confirmed_at, so the
    note is keyed on the cancellation, not the booking."""
    from service.events import rsvp
    o = organiser()
    slug = published(organiser_row=o)
    p = make_person(name='AgainMember')
    g = confirmed_guest(slug, name='Again Member', person_id=p['id'])
    with api_tx() as tx:
        rsvp.member_cancel(tx, p['id'], g['id'])
    with api_tx() as tx:
        tx.execute("UPDATE event_rsvp SET status = 'going', cancelled_at = NULL WHERE id = %(i)s",
                   dict(i=g['id']))
        # A new cancellation is a new moment (NOW() is the transaction's).
        tx.execute("SELECT pg_sleep(1.1)")
    with api_tx() as tx:
        rsvp.member_cancel(tx, p['id'], g['id'])
    assert len(_rows('event_place_cancelled', o['id'])) == 2
