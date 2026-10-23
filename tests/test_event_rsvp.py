"""RSVP without an account (TEC-1845): the RSVP, confirming by the emailed
link, cancelling, and a member confirmed at once. A place is held only
once confirmed, and the last place goes to one guest."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')

# The confirm link's token is only ever emailed: capture it as queued.
TOKENS: dict[int, str] = {}


@pytest.fixture(autouse=True)
def _capture_tokens(monkeypatch):
    TOKENS.clear()
    monkeypatch.setattr('service.events.mail.queue_confirm',
                        lambda tx, rid, token: TOKENS.__setitem__(rid, token) or 1)


def _rsvp(slug, email):
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT r.* FROM event_rsvp r JOIN event e ON e.id = r.event_id
                WHERE e.slug = %(s)s AND r.normalized_email = %(e)s""", dict(s=slug, e=email)).fetchone()
    return dict(row) if row else None


def _lead(lead_id):
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM lead WHERE id = %(i)s', dict(i=lead_id)).fetchone())


def _post(client, slug, email, party_size=1, **kw):
    return client.post(f'/events/{slug}/rsvp', json=dict(name=kw.pop('name', 'Hannah Okafor'), email=email,
                                                          party_size=party_size, **kw))


def _rsvp_token(client, slug, email, party_size=1):
    assert _post(client, slug, email, party_size).status_code == 201
    return TOKENS[_rsvp(slug, email)['id']]


def _confirm(token):
    from service.api.decorators import app
    with app.test_client() as c:
        return c.get(f'/rsvp/confirm/{token}')


def _set_event(slug, **cols):
    with api_tx() as tx:
        tx.execute(f"UPDATE event SET {', '.join(f'{k} = %({k})s' for k in cols)} WHERE slug = %(slug)s",
                   dict(cols, slug=slug))


def test_a_visitor_rsvps_and_is_asked_to_check_their_email(client, published):
    slug = published()
    r = client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah Okafor', email='hannah@ahavah-test.invalid', party_size=2))
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': 'hannah@ahavah-test.invalid'}
    assert r.headers['Cache-Control'] == 'no-store'
    row = _rsvp(slug, 'hannah@ahavah-test.invalid')
    assert row['confirmed_at'] is None and row['source'] == f'event:{slug}' and row['new_address'] is True
    lead = _lead(row['lead_id'])
    assert lead['source'] == f'event:{slug}' and lead['marketing_consent'] is False and lead['confirmed_at'] is None
    assert row['id'] in TOKENS


def test_the_box_is_the_only_marketing_consent(client, published):
    slug = published()
    client.post(f'/events/{slug}/rsvp', json=dict(name='A', email='a@ahavah-test.invalid', party_size=1, news=True))
    lead = _lead(_rsvp(slug, 'a@ahavah-test.invalid')['lead_id'])
    assert lead['marketing_consent'] is True and lead['consent_wording'] == 'events-rsvp-news-v1'


def test_confirming_holds_the_place_and_confirms_the_lead(client, published):
    slug = published(capacity=10, show_going=True)
    token = _rsvp_token(client, slug, 'c@ahavah-test.invalid', 3)
    assert client.get(f'/events/{slug}').get_json()['places_left'] == 10
    r = client.get(f'/rsvp/confirm/{token}')
    assert r.status_code == 200 and r.get_json()['rsvp'] == dict(
        name='Hannah Okafor', party_size=3, status='going', confirmed=True, join_offer=False)
    assert client.get(f'/events/{slug}').get_json()['places_left'] == 7
    row = _rsvp(slug, 'c@ahavah-test.invalid')
    assert row['confirmed_at'] is not None and _lead(row['lead_id'])['confirmed_via'] == 'link'
    again = client.get(f'/rsvp/confirm/{token}')
    assert again.status_code == 200 and again.get_json() == r.get_json()


def test_the_venue_and_link_appear_only_once_confirmed(client, published):
    slug = published(venue='14 Elm Street', venue_visibility='confirmed')
    token = _rsvp_token(client, slug, 'v@ahavah-test.invalid')
    assert 'venue' not in client.get(f'/rsvp/{token}').get_json()['event']
    assert client.get(f'/rsvp/confirm/{token}').get_json()['event']['venue'] == '14 Elm Street'
    talk = published(mode='online', online_url='https://meet.example.com/secret', city=None, country=None)
    t2 = _rsvp_token(client, talk, 'v@ahavah-test.invalid')
    assert 'meet.example.com' not in client.get(f'/rsvp/{t2}').get_data(as_text=True)
    assert client.get(f'/rsvp/confirm/{t2}').get_json()['event']['online_url'] == 'https://meet.example.com/secret'


def test_two_guests_confirming_the_last_place_get_one_place(client, published):
    slug = published(capacity=2)
    t1 = _rsvp_token(client, slug, 'a@ahavah-test.invalid', 2)
    t2 = _rsvp_token(client, slug, 'b@ahavah-test.invalid', 2)
    with ThreadPoolExecutor(2) as ex:
        results = [f.result() for f in [ex.submit(_confirm, t1), ex.submit(_confirm, t2)]]
    assert sorted(r.status_code for r in results) == [200, 409]
    assert [r.get_json() for r in results if r.status_code == 409] == [{'error': 'full_now'}]


def test_more_guests_than_places_left_says_how_many_are_left(client, published, confirmed_guest):
    slug = published(capacity=5)
    confirmed_guest(slug, party_size=2)
    r = _post(client, slug, 'm@ahavah-test.invalid', 5)
    assert (r.status_code, r.get_json()) == (409, {'error': 'too_many', 'places_left': 3})
    confirmed_guest(slug, party_size=3)
    r = _post(client, slug, 'm@ahavah-test.invalid', 1)
    assert (r.status_code, r.get_json()) == (409, {'error': 'full', 'places_left': 0})


def test_an_expired_confirm_link_says_so(client, published):
    slug = published()
    token = _rsvp_token(client, slug, 'x@ahavah-test.invalid')
    with api_tx() as tx:
        tx.execute("UPDATE event_rsvp SET confirm_by = NOW() - interval '1 minute' WHERE normalized_email = %(e)s "
                   "AND event_id = (SELECT id FROM event WHERE slug = %(s)s)", dict(e='x@ahavah-test.invalid', s=slug))
    r = client.get(f'/rsvp/confirm/{token}')
    assert (r.status_code, r.get_json()) == (410, {'error': 'expired'})


def test_the_confirm_window_ends_at_the_start(client, published):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    slug = published(starts_at=start)
    _rsvp_token(client, slug, 'w@ahavah-test.invalid')
    assert abs(_rsvp(slug, 'w@ahavah-test.invalid')['confirm_by'] - start) < timedelta(seconds=1)


def test_a_gathering_cancelled_before_the_guest_confirms(client, published, organiser):
    slug = published()
    token = _rsvp_token(client, slug, 'y@ahavah-test.invalid')
    _set_event(slug, status='cancelled')
    r = client.get(f'/rsvp/confirm/{token}')
    assert (r.status_code, r.get_json()) == (409, {'error': 'cancelled_now'})
    r = _post(client, slug, 'z@ahavah-test.invalid')
    assert (r.status_code, r.get_json()) == (409, {'error': 'closed'})


def test_a_gathering_moved_to_start_earlier_takes_no_place_once_it_has_started(client, published):
    slug = published()
    token = _rsvp_token(client, slug, 'early@ahavah-test.invalid')
    _set_event(slug, starts_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    r = client.get(f'/rsvp/confirm/{token}')
    assert (r.status_code, r.get_json()) == (410, {'error': 'expired'})


def test_a_paused_gathering_keeps_its_venue_from_its_guests_and_takes_no_place(client, published):
    slug = published(venue='14 Elm Street', venue_visibility='confirmed')
    going = _rsvp_token(client, slug, 'paused-a@ahavah-test.invalid')
    assert client.get(f'/rsvp/confirm/{going}').status_code == 200
    waiting = _rsvp_token(client, slug, 'paused-b@ahavah-test.invalid')
    _set_event(slug, paused_at=datetime.now(timezone.utc))
    assert 'venue' not in client.get(f'/rsvp/{going}').get_json()['event']
    assert 'Elm Street' not in client.get(f'/rsvp/{going}/calendar.ics').get_data(as_text=True)
    assert client.get(f'/rsvp/confirm/{waiting}').status_code == 404
    assert _rsvp(slug, 'paused-b@ahavah-test.invalid')['confirmed_at'] is None
    assert client.post(f'/rsvp/{going}/cancel').get_json()['rsvp']['status'] == 'cancelled'


def test_cancelling_frees_the_place(client, published):
    slug = published(capacity=2)
    token = _rsvp_token(client, slug, 'f@ahavah-test.invalid', 2)
    client.get(f'/rsvp/confirm/{token}')
    assert client.get(f'/events/{slug}').get_json()['state'] == 'full'
    r = client.post(f'/rsvp/{token}/cancel')
    assert r.status_code == 200 and r.get_json()['rsvp']['status'] == 'cancelled'
    assert client.get(f'/events/{slug}').get_json()['places_left'] == 2


def test_rsvping_again_keeps_one_row(client, published):
    slug = published()
    _post(client, slug, 'r@ahavah-test.invalid', 1)
    first = _rsvp(slug, 'r@ahavah-test.invalid')
    _post(client, slug, 'R@ahavah-test.invalid', 4, share_email=True)
    again = _rsvp(slug, 'r@ahavah-test.invalid')
    assert again['id'] == first['id'] and again['party_size'] == 4 and again['share_email_with_organiser'] is True
    assert again['resends'] == 1 and again['token_hash'] != first['token_hash']


def test_a_cancelled_place_can_be_taken_again(client, published):
    slug = published()
    token = _rsvp_token(client, slug, 'k@ahavah-test.invalid')
    client.get(f'/rsvp/confirm/{token}')
    client.post(f'/rsvp/{token}/cancel')
    _post(client, slug, 'k@ahavah-test.invalid')
    row = _rsvp(slug, 'k@ahavah-test.invalid')
    assert (row['status'], row['confirmed_at'], row['resends']) == ('going', None, 0)


def test_a_signed_in_member_is_confirmed_at_once_and_is_not_a_lead(client, published, make_person, sign_in):
    slug = published()
    p = make_person(name='Ruth Adeyemi', gender='Woman', email='ruth-member@ahavah-test.invalid')
    headers = sign_in(p)
    assert client.get('/rsvp/me', headers=headers).get_json() == {'name': 'Ruth', 'email': 'ruth-member@ahavah-test.invalid'}
    r = client.post(f'/events/{slug}/rsvp', headers=headers, json=dict(name='Ruth', party_size=1))
    assert r.status_code == 201 and r.get_json()['state'] == 'confirmed'
    row = _rsvp(slug, 'ruth-member@ahavah-test.invalid')
    assert row['person_id'] == p['id'] and row['confirmed_at'] is not None and row['lead_id'] is None
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM lead WHERE email = 'ruth-member@ahavah-test.invalid'").fetchone() is None
    assert client.get(f"/rsvp/{r.get_json()['token']}").get_json()['rsvp']['confirmed'] is True
    assert TOKENS == {}


def test_a_refused_address_is_answered_as_a_send_and_nothing_is_written(client, published, monkeypatch):
    monkeypatch.setattr('service.leads.mail_refusal', lambda **k: 'honeypot')
    slug = published()
    r = _post(client, slug, 'bot@ahavah-test.invalid', website='http://spam.example')
    assert (r.status_code, r.get_json()) == (201, {'state': 'check_email', 'email': 'bot@ahavah-test.invalid'})
    assert _rsvp(slug, 'bot@ahavah-test.invalid') is None and TOKENS == {}
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM lead WHERE email = 'bot@ahavah-test.invalid'").fetchone() is None


def test_the_email_link_is_the_web_page_not_the_api():
    from service.config import WEB_BASE_URL
    from service.events.mail import confirm_url
    assert confirm_url('tok') == f'{WEB_BASE_URL}/rsvp/confirm/tok'


def test_sending_it_again_stops_after_3(client, published):
    slug = published()
    codes = [_post(client, slug, 's@ahavah-test.invalid').status_code for _ in range(4)]
    assert codes == [201, 201, 201, 429]
    assert _post(client, slug, 's@ahavah-test.invalid').get_json() == {'error': 'too_many_tries'}


def test_party_size_and_name_are_checked(client, published):
    slug = published()
    for party, name, reason in ((0, 'A', 'bad_party'), (11, 'A', 'bad_party'), (1, '', 'bad_name')):
        r = _post(client, slug, 'p@ahavah-test.invalid', party, name=name)
        assert (r.status_code, r.get_json()) == (400, {'error': reason})
    r = _post(client, slug, 'not-an-address', 1)
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_email'})


def test_an_unknown_token_or_gathering_is_not_found(client, published):
    assert client.get('/rsvp/' + 'x' * 32).status_code == 404
    assert client.get('/rsvp/confirm/' + 'x' * 32).status_code == 404
    assert _post(client, 'no-such-gathering', 'n@ahavah-test.invalid').status_code == 404


def test_everything_is_dark_until_live(client, published, monkeypatch):
    slug = published()
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    assert _post(client, slug, 'd@ahavah-test.invalid').status_code == 404
    assert client.get('/rsvp/' + 'x' * 32).status_code == 404
