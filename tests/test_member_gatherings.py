"""Your gatherings > Going (TEC-1845, in-app entry plan, release 2): a
member-only list of the member's own places, upcoming and past, by the
RSVP's person (which link_rsvps_to_person sets at sign-up for places
booked before joining). Public fields of each gathering only, the place's
state and the path of the member's own view of it. Dark unless events_live
is on and app_entries lets the member in."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service.events import rsvp as rsvp_mod

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'entries_on')

NOW = datetime.now(timezone.utc)


@pytest.fixture
def entries_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')


@pytest.fixture
def member(make_person, sign_in):
    address = f'going-{uuid4().hex[:10]}@ahavah-test.invalid'
    p = make_person(name='Miriam Going', gender='Woman', email=address)
    return dict(p, email=address, headers=sign_in(p))


def _mine(client, member):
    r = client.get('/rsvp/mine', headers=member['headers'])
    assert r.status_code == 200, r.get_json()
    assert r.headers['Cache-Control'] == 'no-store'
    return r.get_json()


def _slugs(items):
    return [i['gathering']['slug'] for i in items]


def test_dark_while_app_entries_does_not_let_the_member_in(client, member, published, confirmed_guest,
                                                           monkeypatch):
    rid = confirmed_guest(published(), person_id=member['id'])['id']
    for setting, allow in (('off', str(member['id'])), ('', ''), ('owner', ''), ('owner', '1')):
        monkeypatch.setenv('AHAVAH_APP_ENTRIES', setting)
        monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', allow)
        for path in ('/rsvp/mine', f'/rsvp/mine/{rid}'):
            r = client.get(path, headers=member['headers'])
            assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'}), (setting, path)


def test_owner_only_lets_the_listed_member_in(client, member, published, confirmed_guest, monkeypatch):
    slug = published()
    confirmed_guest(slug, person_id=member['id'])
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', member['email'].upper())
    assert _slugs(_mine(client, member)['upcoming']) == [slug]


def test_dark_while_events_live_is_off(client, member, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    assert client.get('/rsvp/mine', headers=member['headers']).status_code == 404


def test_members_only(client, tool_visitor):
    _, visitor = tool_visitor()
    for headers in ({}, visitor):
        r = client.get('/rsvp/mine', headers=headers)
        assert r.status_code in (400, 401, 403)
        assert 'upcoming' not in r.get_data(as_text=True)


def test_the_members_upcoming_and_past_places_and_no_one_elses(client, member, make_person, published,
                                                               confirmed_guest):
    later = published(starts_at=NOW + timedelta(days=20))
    soon = published(starts_at=NOW + timedelta(days=3))
    gave_up = published(starts_at=NOW + timedelta(days=10))
    long_ago = published(starts_at=NOW - timedelta(days=30))
    yesterday = published(starts_at=NOW - timedelta(days=1, hours=4))
    others = published(starts_at=NOW + timedelta(days=4))
    for slug in (later, soon, gave_up, long_ago, yesterday):
        confirmed_guest(slug, person_id=member['id'], email=member['email'])
    cancelled = confirmed_guest(published(starts_at=NOW + timedelta(days=11)),
                                person_id=member['id'], email=member['email'])
    with api_tx() as tx:
        tx.execute("UPDATE event_rsvp SET status = 'cancelled', cancelled_at = NOW() WHERE id = %(i)s",
                   dict(i=cancelled['id']))
    someone = make_person(name='Someone Else')
    confirmed_guest(others, person_id=someone['id'])
    out = _mine(client, member)
    assert _slugs(out['upcoming'])[:2] == [soon, gave_up]
    assert later in _slugs(out['upcoming']) and others not in _slugs(out['upcoming'])
    assert [i['state'] for i in out['upcoming']] == ['going', 'going', 'cancelled', 'going']
    # Past: the most recent first.
    assert _slugs(out['past']) == [yesterday, long_ago]
    assert out['more_upcoming'] is False and out['more_past'] is False


def test_public_fields_only(client, member, published, confirmed_guest):
    hall = published(venue='14 Elm Street, Dallas', venue_visibility='confirmed')
    talk = published(mode='online', online_url='https://meet.example.com/secret-call', city=None,
                     country=None, starts_at=NOW + timedelta(days=31))
    for slug in (hall, talk):
        confirmed_guest(slug, person_id=member['id'], email=member['email'], name='Miriam Going')
    out = _mine(client, member)
    text = repr(out)
    assert 'Elm Street' not in text and 'secret-call' not in text
    assert member['email'] not in text and 'Miriam' not in text
    first, second = out['upcoming']
    assert set(first) == {'id', 'state', 'party_size', 'gathering', 'place_path'}
    assert set(first['gathering']) == {'slug', 'title', 'starts_at', 'ends_at', 'tz', 'tz_label', 'mode',
                                       'city', 'country', 'cancelled'}
    assert (first['gathering']['city'], first['gathering']['mode']) == ('Dallas', 'in_person')
    assert (second['gathering']['city'], second['gathering']['mode']) == (None, 'online')
    assert first['place_path'] == f"/rsvp/mine/{first['id']}"


def test_a_cancelled_gathering_says_so(client, member, published, confirmed_guest):
    slug = published(status='cancelled', cancel_note='The hall flooded.')
    confirmed_guest(slug, person_id=member['id'])
    (item,) = _mine(client, member)['upcoming']
    assert item['gathering']['cancelled'] is True and 'flooded' not in repr(item)


def test_a_paused_draft_or_pending_gathering_is_left_out(client, member, published, confirmed_guest):
    for over in (dict(paused_at=NOW), dict(status='pending', published_at=None)):
        confirmed_guest(published(**over), person_id=member['id'])
    out = _mine(client, member)
    assert out['upcoming'] == [] and out['past'] == []


def test_an_erased_place_is_left_out(client, member, published, confirmed_guest):
    rid = confirmed_guest(published(starts_at=NOW - timedelta(days=100)), person_id=member['id'])['id']
    with api_tx() as tx:
        tx.execute("""UPDATE event_rsvp SET name = NULL, email = NULL, normalized_email = NULL,
                             token_hash = NULL, erased_at = NOW() WHERE id = %(i)s""", dict(i=rid))
    assert _mine(client, member)['past'] == []


def test_a_place_booked_before_joining_shows_once_linked(client, member, published, confirmed_guest):
    slug = published()
    confirmed_guest(slug, email=member['email'])  # as a visitor, before joining
    assert _mine(client, member)['upcoming'] == []
    with api_tx() as tx:
        tx.execute('UPDATE person SET normalized_email = %(e)s WHERE id = %(i)s',
                   dict(e=member['email'], i=member['id']))
        from service.events.retention import link_rsvps_to_person
        link_rsvps_to_person(tx, member['id'])
    assert _slugs(_mine(client, member)['upcoming']) == [slug]


def test_each_list_is_capped_and_says_there_is_more(client, member, published, confirmed_guest,
                                                    monkeypatch):
    monkeypatch.setattr(rsvp_mod, 'GOING_UPCOMING_MAX', 2)
    monkeypatch.setattr(rsvp_mod, 'GOING_PAST_MAX', 1)
    for d in (3, 4, 5):
        confirmed_guest(published(starts_at=NOW + timedelta(days=d)), person_id=member['id'])
    for d in (3, 4):
        confirmed_guest(published(starts_at=NOW - timedelta(days=d)), person_id=member['id'])
    out = _mine(client, member)
    assert (len(out['upcoming']), out['more_upcoming']) == (2, True)
    assert (len(out['past']), out['more_past']) == (1, True)


def test_the_members_own_place_shows_as_their_link_does(client, member, make_person, sign_in, published,
                                                       confirmed_guest):
    hall = published(venue='14 Elm Street, Dallas', venue_visibility='confirmed')
    guest = confirmed_guest(hall, person_id=member['id'], email=member['email'], party_size=2)
    mine = client.get(f"/rsvp/mine/{guest['id']}", headers=member['headers'])
    by_link = client.get(f"/rsvp/{guest['token']}")
    assert mine.status_code == 200 and mine.headers['Cache-Control'] == 'no-store'
    assert mine.get_json() == by_link.get_json()
    assert mine.get_json()['event']['venue'] == '14 Elm Street, Dallas'
    # Never someone else's place.
    other = make_person(name='Not Theirs')
    r = client.get(f"/rsvp/mine/{guest['id']}", headers=sign_in(other))
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})
    assert client.get('/rsvp/mine/999999999', headers=member['headers']).status_code == 404


def test_a_past_place_closes_as_its_link_does(client, member, published, confirmed_guest):
    gone = published(starts_at=NOW - timedelta(days=3))
    guest = confirmed_guest(gone, person_id=member['id'])
    (item,) = _mine(client, member)['past']
    assert item['place_path'] is None
    assert client.get(f"/rsvp/mine/{guest['id']}", headers=member['headers']).status_code == 404


def test_an_unconfirmed_place_is_not_the_members_place(client, member, published, confirmed_guest):
    """As in the list: a place never confirmed holds nothing, so the member's
    own view of it is not found, as the list leaves it out."""
    guest = confirmed_guest(published(), person_id=member['id'])
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET confirmed_at = NULL WHERE id = %(i)s', dict(i=guest['id']))
    for path in (f"/rsvp/mine/{guest['id']}", f"/rsvp/mine/{guest['id']}/calendar.ics"):
        r = client.get(path, headers=member['headers'])
        assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'}), path
    r = client.post(f"/rsvp/mine/{guest['id']}/cancel", headers=member['headers'])
    assert r.status_code == 404


def test_the_member_cancels_their_own_place_from_the_app(client, member, make_person, sign_in, published,
                                                         confirmed_guest):
    """Design 4.7: Cancel my place, without the emailed link's token."""
    guest = confirmed_guest(published(), person_id=member['id'], party_size=2)
    other = make_person(name='Not Theirs')
    r = client.post(f"/rsvp/mine/{guest['id']}/cancel", headers=sign_in(other))
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})
    assert client.post(f"/rsvp/mine/{guest['id']}/cancel").status_code in (400, 401, 403)
    r = client.post(f"/rsvp/mine/{guest['id']}/cancel", headers=member['headers'])
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json()['rsvp']['status'] == 'cancelled'
    # The same answer again, and the emailed link agrees.
    again = client.post(f"/rsvp/mine/{guest['id']}/cancel", headers=member['headers'])
    assert again.get_json()['rsvp']['status'] == 'cancelled'
    assert client.get(f"/rsvp/{guest['token']}").get_json()['rsvp']['status'] == 'cancelled'


def test_the_members_calendar_file_from_the_app(client, member, make_person, sign_in, published,
                                                confirmed_guest):
    hall = published(venue='14 Elm Street, Dallas', venue_visibility='confirmed')
    guest = confirmed_guest(hall, person_id=member['id'])
    r = client.get(f"/rsvp/mine/{guest['id']}/calendar.ics", headers=member['headers'])
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith('text/calendar')
    assert r.headers['Cache-Control'] == 'no-store'
    by_link = client.get(f"/rsvp/{guest['token']}/calendar.ics")
    body = r.get_data(as_text=True)
    assert 'Elm Street' in body
    strip = lambda t: [line for line in t.splitlines() if not line.startswith('DTSTAMP')]
    assert strip(body) == strip(by_link.get_data(as_text=True))
    other = make_person(name='Not Theirs')
    assert client.get(f"/rsvp/mine/{guest['id']}/calendar.ics", headers=sign_in(other)).status_code == 404


def test_cancel_and_calendar_are_dark_while_app_entries_is_off(client, member, published, confirmed_guest,
                                                               monkeypatch):
    rid = confirmed_guest(published(), person_id=member['id'])['id']
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'off')
    assert client.get(f'/rsvp/mine/{rid}/calendar.ics', headers=member['headers']).status_code == 404
    assert client.post(f'/rsvp/mine/{rid}/cancel', headers=member['headers']).status_code == 404
    with api_tx() as tx:
        status = tx.execute('SELECT status FROM event_rsvp WHERE id = %(i)s', dict(i=rid)).fetchone()['status']
    assert status == 'going'
