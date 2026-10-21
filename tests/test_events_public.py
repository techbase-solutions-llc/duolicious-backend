"""The public read (TEC-1845): gatherings by region, one gathering, views
and the country list. The venue and the call link never leave the API in
a public response unless the organiser made the venue public."""
from datetime import date, datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')


def _set(slug, **cols):
    with api_tx() as tx:
        tx.execute(f"UPDATE event SET {', '.join(f'{k} = %({k})s' for k in cols)} WHERE slug = %(slug)s",
                   dict(cols, slug=slug))


def test_a_region_shows_its_own_and_every_online_gathering(client, published, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    dallas = published(country='United States', city='Dallas')
    kampala = published(country='Uganda', city='Kampala')
    talk = published(mode='online', online_url='https://meet.example.com/a', city=None, country=None)
    slugs = [e['slug'] for e in client.get('/events?region=north-america&limit=50').get_json()['events']]
    assert dallas in slugs and talk in slugs and kampala not in slugs


def test_the_list_is_by_start_and_checks_its_region(client, published):
    soon = published(starts_at=datetime.now(timezone.utc) + timedelta(days=2))
    later = published(starts_at=datetime.now(timezone.utc) + timedelta(days=3))
    r = client.get('/events?limit=50')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'public, max-age=60'
    slugs = [e['slug'] for e in r.get_json()['events']]
    assert slugs.index(soon) < slugs.index(later)
    assert client.get('/events?region=atlantis').get_json() == {'error': 'bad_region'}


def test_the_public_never_sees_the_venue_or_the_call_link_unless_made_public(client, published, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    hidden = published(venue='14 Elm Street', venue_visibility='confirmed')
    shown = published(venue='Grace Fellowship hall, 14 Elm Street, Dallas', venue_visibility='public')
    talk = published(mode='online', online_url='https://meet.example.com/secret', city=None, country=None)
    assert 'venue' not in client.get(f'/events/{hidden}').get_json()
    assert client.get(f'/events/{shown}').get_json()['venue'] == 'Grace Fellowship hall, 14 Elm Street, Dallas'
    assert 'meet.example.com' not in client.get(f'/events/{talk}').get_data(as_text=True)
    assert 'Elm Street' not in client.get('/events?limit=50').get_data(as_text=True)


def test_going_shows_only_when_the_organiser_shows_it(client, published, confirmed_guest):
    quiet = published(show_going=False)
    open_ = published(show_going=True)
    for slug in (quiet, open_):
        confirmed_guest(slug, party_size=3)
    assert 'going' not in client.get(f'/events/{quiet}').get_json()
    assert client.get(f'/events/{open_}').get_json()['going'] == 3


def test_full_cancelled_and_ended_say_so(client, published, confirmed_guest):
    full = published(capacity=2)
    confirmed_guest(full, party_size=2)
    view = client.get(f'/events/{full}').get_json()
    assert (view['state'], view['places_left']) == ('full', 0)
    roomy = published(capacity=5)
    confirmed_guest(roomy, party_size=2)
    assert client.get(f'/events/{roomy}').get_json()['places_left'] == 3
    gone = published(status='cancelled', cancel_note='The hall flooded.')
    view = client.get(f'/events/{gone}').get_json()
    assert (view['state'], view['cancel_note']) == ('cancelled', 'The hall flooded.')
    ended = published(starts_at=datetime.now(timezone.utc) - timedelta(days=2))
    assert client.get(f'/events/{ended}').get_json()['state'] == 'ended'
    assert ended not in [e['slug'] for e in client.get('/events?limit=50').get_json()['events']]


def test_a_draft_pending_or_paused_gathering_is_not_found(client, organiser, published):
    for over in (dict(status='draft', published_at=None), dict(status='pending', published_at=None),
                 dict(paused_at=datetime.now(timezone.utc))):
        slug = published(**over)
        assert client.get(f'/events/{slug}').status_code == 404
        assert slug not in [e['slug'] for e in client.get('/events?limit=50').get_json()['events']]
    assert client.get('/events/no-such-gathering').status_code == 404


def test_a_change_shows_for_14_days_and_not_after_the_start(client, published):
    slug = published()
    before = dict(date='Saturday 7 November 2026', time='6pm to 9pm, Central Time', place='Dallas',
                  venue='14 Elm Street', mode='in_person')
    after = dict(before, time='7pm to 10pm, Central Time')
    import json
    _set(slug, changed_at=datetime.now(timezone.utc) - timedelta(days=13),
         change_before=json.dumps(before), change_after=json.dumps(after))
    changed = client.get(f'/events/{slug}').get_json()['changed']
    assert changed['after']['time'] == '7pm to 10pm, Central Time'
    assert 'venue' not in changed['before'] and 'Elm Street' not in json.dumps(changed)
    _set(slug, changed_at=datetime.now(timezone.utc) - timedelta(days=15))
    assert client.get(f'/events/{slug}').get_json().get('changed') is None
    _set(slug, changed_at=datetime.now(timezone.utc), starts_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert client.get(f'/events/{slug}').get_json().get('changed') is None


def test_views_are_counted_per_day_and_bots_are_not(client, published):
    slug = published()
    assert client.post(f'/events/{slug}/view').status_code == 204
    client.post(f'/events/{slug}/view')
    client.post(f'/events/{slug}/view', headers={'User-Agent': 'WhatsApp link preview'})
    client.post(f'/events/{slug}/view', headers={'User-Agent': 'Googlebot/2.1'})
    with api_tx('read committed') as tx:
        rows = tx.execute(
            """SELECT d.day, d.views FROM event_view_day d JOIN event e ON e.id = d.event_id
                WHERE e.slug = %(s)s""", dict(s=slug)).fetchall()
    assert [(r['day'], r['views']) for r in rows] == [(datetime.now(timezone.utc).date(), 2)]


def test_the_countries_carry_their_region(client):
    r = client.get('/events/countries')
    assert r.headers['Cache-Control'] == 'public, max-age=86400'
    countries = {c['name']: c['region'] for c in r.get_json()['countries']}
    assert countries['Barbados'] == 'north-america' and len(countries) == 243


def test_the_list_is_closed_until_its_switch_but_a_gathering_page_is_not(client, published, monkeypatch):
    slug = published()
    monkeypatch.delenv('AHAVAH_EVENTS_LIST_ENABLED')
    assert client.get('/events').status_code == 404
    assert client.get(f'/events/{slug}').status_code == 200


def test_everything_is_dark_until_live(client, published, monkeypatch):
    slug = published()
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    for path in ('/events', f'/events/{slug}', '/events/countries'):
        assert client.get(path).status_code == 404
    assert client.post(f'/events/{slug}/view').status_code == 404
    assert client.get('/events/status').status_code == 200


def test_a_card_carries_the_organiser_and_the_feast_label(client, published):
    slug = published(feast='tabernacles', tags=['singles_welcome', 'marriage_preparation'])
    view = client.get(f'/events/{slug}').get_json()
    assert view['organiser'] == {'name': 'Grace Fellowship', 'kind': 'fellowship_leader'}
    assert view['feast_label'] == 'Tabernacles' and view['state'] == 'open'
    assert view['starts_at'].endswith('+00:00') and view['cover_url'] is None
