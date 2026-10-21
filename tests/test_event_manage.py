"""Organisers manage their gatherings (TEC-1845): create, edit, publish,
cancel, the lists, the RSVP list, attendance and the posts."""
import json
from datetime import datetime, time, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')

SCAM = 'Send me money by Western Union and gift cards, my darling'


def _iso(days: int, hour: int = 0) -> str:
    day = (datetime.now(timezone.utc) + timedelta(days=days)).date()
    return datetime.combine(day, time(hour, 0), timezone.utc).isoformat()


def draft(**over) -> dict:
    """Task 3's GOOD, 30 days ahead."""
    return {**dict(title='Marriage preparation evening', starts_at=_iso(30, 0), ends_at=_iso(30, 3),
                   tz='America/Chicago', tz_label='Central Time', mode='in_person', city='Dallas',
                   country='United States', venue='Grace Fellowship hall, 14 Elm Street, Dallas',
                   venue_visibility='confirmed',
                   description='An evening for single believers who hope to marry.', capacity=40,
                   tags=['singles_welcome', 'marriage_preparation'], feast=None, show_going=False),
            **over}


@pytest.fixture
def create(client, event_cleanup):
    def _create(o, **over) -> str:
        r = client.post('/organiser/events', headers=o['headers'], json=draft(**over))
        assert r.status_code == 201, r.get_json()
        slug = r.get_json()['slug']
        event_cleanup(slug)
        return slug
    return _create


def _row(slug):
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone())


def _post_keys(slug):
    with api_tx('read committed') as tx:
        return [r['request_key'] for r in tx.execute(
            """SELECT DISTINCT request_key FROM publishing_queue
                WHERE request_key LIKE %(p)s AND status <> 'cancelled' ORDER BY request_key""",
            dict(p=f'event:{slug}:%')).fetchall()]


def _post_payload(key):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT payload FROM publishing_queue WHERE request_key = %(k)s LIMIT 1',
                          dict(k=key)).fetchone()['payload']


def _post_statuses(slug):
    """How many posts (request keys, each with a row per platform) are in
    each status."""
    with api_tx('read committed') as tx:
        rows = tx.execute(
            """SELECT status, COUNT(DISTINCT request_key)::int AS n FROM publishing_queue
                WHERE request_key LIKE %(p)s GROUP BY status""",
            dict(p=f'event:{slug}:%')).fetchall()
    return {r['status']: r['n'] for r in rows}


@pytest.fixture
def _published(client, create):
    def _make(organiser, **over):
        o = organiser()
        slug = create(o, **over)
        assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {
            'status': 'published'}
        return o, slug
    return _make


def test_a_new_organisers_first_gathering_waits_for_approval(client, organiser, create):
    o = organiser(approved=False)
    slug = create(o)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'pending'}
    assert _row(slug)['flag_reason'] == 'new_organiser'
    assert client.get(f'/events/{slug}').status_code == 404


def test_an_approved_organiser_publishes_and_the_two_posts_are_queued(client, organiser, create):
    o = organiser()
    slug = create(o)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'published'}
    keys = _post_keys(slug)
    assert sorted(k.rsplit(':', 1)[1] for k in keys) == ['d10', 'd2']
    payload = _post_payload(keys[0])
    assert payload['event_title'] == 'Marriage preparation evening' and 'Elm Street' not in json.dumps(payload)
    assert payload['city_or_online'] == 'Dallas' and payload['organiser_name'] == 'Grace Fellowship'


def test_flagged_text_waits_even_for_an_approved_organiser(client, organiser, create):
    o = organiser()
    slug = create(o, description=SCAM)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'pending'}
    assert _row(slug)['flag_reason'] == 'scam' and _post_keys(slug) == []


def test_moving_a_published_gathering_emails_guests_once_and_requeues_its_posts(
        client, organiser, confirmed_guest, monkeypatch, _published):
    calls = []
    monkeypatch.setattr('service.events.mail.queue_change', lambda tx, eid: calls.append(eid) or 1)
    o, slug = _published(organiser)
    confirmed_guest(slug)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'],
                     json=dict(starts_at=_iso(days=31, hour=1), ends_at=_iso(days=31, hour=4)))
    assert r.get_json()['notified'] == 1 and len(calls) == 1
    row = _row(slug)
    assert row['changed_at'] is not None and row['change_before']['date'] != row['change_after']['date']
    assert _post_statuses(slug) == {'cancelled': 2, 'awaiting_render': 2}


def test_editing_only_the_description_tells_nobody(client, organiser, confirmed_guest, monkeypatch, _published):
    calls = []
    monkeypatch.setattr('service.events.mail.queue_change', lambda tx, eid: calls.append(eid) or 1)
    o, slug = _published(organiser)
    confirmed_guest(slug)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'],
                     json=dict(description='A shared meal and time to talk.'))
    assert r.status_code == 200 and r.get_json()['notified'] == 0 and calls == []
    assert _row(slug)['changed_at'] is None and _row(slug)['description'] == 'A shared meal and time to talk.'


def test_new_flagged_text_on_a_published_gathering_sends_it_back(client, organiser, _published):
    o, slug = _published(organiser)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'], json=dict(description=SCAM))
    assert r.get_json()['event']['status'] == 'pending'
    assert _row(slug)['flag_reason'] == 'scam' and _post_statuses(slug) == {'cancelled': 2}


def test_a_bad_edit_is_refused(client, organiser, _published):
    o, slug = _published(organiser)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'], json=dict(capacity=0))
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_capacity'})


def test_cancelling_tells_confirmed_guests_and_cancels_the_posts(client, organiser, confirmed_guest, monkeypatch, _published):
    calls = []
    monkeypatch.setattr('service.events.mail.queue_cancelled', lambda tx, eid: calls.append(eid) or 1)
    o, slug = _published(organiser)
    confirmed_guest(slug)
    r = client.post(f'/organiser/events/{slug}/cancel', headers=o['headers'],
                    json=dict(note='The hall flooded. We will pick a new date soon.'))
    assert r.get_json() == {'notified': 1} and len(calls) == 1
    row = _row(slug)
    assert row['status'] == 'cancelled' and row['cancel_note'] == 'The hall flooded. We will pick a new date soon.'
    assert _post_statuses(slug) == {'cancelled': 2}


def test_a_flagged_cancel_note_is_dropped_but_the_cancellation_goes(client, organiser, monkeypatch, _published):
    monkeypatch.setattr('service.events.mail.queue_cancelled', lambda tx, eid: 0)
    o, slug = _published(organiser)
    assert client.post(f'/organiser/events/{slug}/cancel', headers=o['headers'], json=dict(note=SCAM)).status_code == 200
    row = _row(slug)
    assert (row['cancel_note'], row['flag_reason'], row['status']) == (None, 'scam', 'cancelled')


def test_the_lists_group_by_status(client, organiser, create):
    o = organiser()
    a_draft = create(o)
    a_pending = create(o, description=SCAM)
    client.post(f'/organiser/events/{a_pending}/publish', headers=o['headers'])
    a_published = create(o)
    client.post(f'/organiser/events/{a_published}/publish', headers=o['headers'])
    a_cancelled = create(o)
    client.post(f'/organiser/events/{a_cancelled}/cancel', headers=o['headers'], json={})
    an_ended = create(o)
    with api_tx() as tx:
        tx.execute("""UPDATE event SET status = 'published', starts_at = NOW() - interval '2 days',
                                       ends_at = NOW() - interval '1 day' WHERE slug = %(s)s""",
                   dict(s=an_ended))
    groups = client.get('/organiser/me', headers=o['headers']).get_json()['groups']
    assert {k: [g['slug'] for g in v] for k, v in groups.items()} == dict(
        drafts=[a_draft], waiting=[a_pending], published=[a_published], cancelled=[a_cancelled],
        ended=[an_ended])


def test_the_rsvp_list_shows_an_email_only_where_the_guest_shared_it(client, organiser, confirmed_guest, _published):
    o, slug = _published(organiser)
    confirmed_guest(slug, name='Hannah Okafor', party_size=2, share=True)
    confirmed_guest(slug, name='Lydia Cruz', share=False)
    body = client.get(f'/organiser/events/{slug}/rsvps', headers=o['headers']).get_json()
    rows = {g['name']: g for g in body['going']}
    assert 'email' in rows['Hannah Okafor'] and 'email' not in rows['Lydia Cruz']
    assert body['total_going'] == 3 and body['can_mark'] is False


def test_attendance_is_marked_only_once_it_has_started(client, organiser, confirmed_guest, _published):
    o, slug = _published(organiser)
    g = confirmed_guest(slug)
    url = f"/organiser/events/{slug}/rsvps/{g['id']}/attended"
    r = client.post(url, headers=o['headers'], json=dict(attended=True))
    assert (r.status_code, r.get_json()) == (409, {'error': 'not_started'})
    with api_tx() as tx:
        tx.execute("UPDATE event SET starts_at = NOW() - interval '1 hour' WHERE slug = %(s)s", dict(s=slug))
    assert client.post(url, headers=o['headers'], json=dict(attended=True)).status_code == 204
    going = client.get(f'/organiser/events/{slug}/rsvps', headers=o['headers']).get_json()['going']
    assert going[0]['attended'] is True


def test_another_organisers_gathering_is_not_found(client, organiser, _published):
    a, slug = _published(organiser)
    b = organiser()
    h = b['headers']
    assert client.get(f'/organiser/events/{slug}', headers=h).status_code == 404
    assert client.patch(f'/organiser/events/{slug}', headers=h, json=dict(title='Mine now')).status_code == 404
    assert client.post(f'/organiser/events/{slug}/publish', headers=h).status_code == 404
    assert client.post(f'/organiser/events/{slug}/cancel', headers=h, json={}).status_code == 404
    assert client.get(f'/organiser/events/{slug}/rsvps', headers=h).status_code == 404
    assert client.get(f'/organiser/events/{slug}', headers=a['headers']).get_json()['preview'] is True


def test_a_gathering_that_has_started_cannot_be_published(client, organiser, create):
    o = organiser()
    slug = create(o)
    with api_tx() as tx:
        tx.execute("UPDATE event SET starts_at = NOW() - interval '1 hour' WHERE slug = %(s)s", dict(s=slug))
    r = client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    assert (r.status_code, r.get_json()) == (409, {'error': 'started'})


def test_the_post_caption_names_the_city_and_never_the_venue():
    from service.events.manage import post_caption
    start = datetime(2026, 11, 8, 0, tzinfo=timezone.utc)
    ev = dict(title='Marriage preparation evening', starts_at=start, ends_at=start + timedelta(hours=3),
              tz='America/Chicago', tz_label='Central Time', mode='in_person', city='Dallas',
              venue='14 Elm Street', organiser_name='Grace Fellowship')
    assert post_caption(ev) == ('Marriage preparation evening. Saturday 7 November 2026, Dallas. '
                                'Hosted by Grace Fellowship.')
