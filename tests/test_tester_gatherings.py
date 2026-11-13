"""A tester's gathering shows only to testers (TEC-2085, decision 3 as
revised on 13 Nov 2026; TEC-2135).

The owner's ruling of 6 Nov: testers and members never see or reach each
other anywhere. A gathering whose organiser is a tester's (made in the app
by a tester, or under a tester's address) never reaches a member or a
signed-out visitor: not on /events, its page, the RSVP form, the member
emails, the counts or the social queue. Testers find testers' gatherings
as members find members'. Staff see everything in Admin > Events, with the
test label.

The web's server-side reads (a gathering's page, its schema.org data and
share image, the sitemap) send no session, so they are the signed-out
visitor here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.testers import forget_tester_emails

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')


def _grant_tester(person):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['tester']::TEXT[] WHERE id = %(i)s",
                   dict(i=person['id']))
    forget_tester_emails()


@pytest.fixture
def world(make_person, sign_in, organiser):
    """Asher, a member; Tobit, a tester; and two approved organisers: the
    member's (made in the app by Asher) and the tester's (made in the app
    by Tobit)."""
    asher = make_person(name='GatherAsher', gender='Man')
    tobit = make_person(name='GatherTobit', gender='Man')
    _grant_tester(tobit)
    member_org, tester_org = organiser(), organiser(name='Labs test fellowship')
    with api_tx() as tx:
        for org, person in ((member_org, asher), (tester_org, tobit)):
            tx.execute('UPDATE organiser SET member_person_id = %(p)s WHERE id = %(o)s',
                       dict(p=person['id'], o=org['id']))
    return dict(asher=asher, tobit=tobit, member_org=member_org, tester_org=tester_org,
                member=sign_in(asher), tester=sign_in(tobit))


def _slugs(client, headers=None, query='?limit=50'):
    r = client.get(f'/events{query}', headers=headers or {})
    assert r.status_code == 200
    return [e['slug'] for e in r.get_json()['events']]


def test_the_list_hides_a_testers_gathering_from_members_and_visitors(client, world, published):
    theirs = published(organiser_row=world['member_org'])
    test = published(organiser_row=world['tester_org'])
    for headers in (None, world['member']):
        slugs = _slugs(client, headers)
        assert theirs in slugs and test not in slugs
        assert test not in _slugs(client, headers, '?region=north-america&limit=50')
    # A tester sees a tester's gathering only, never a member's (both ways,
    # decided 13 Nov 2026).
    slugs = _slugs(client, world['tester'])
    assert theirs not in slugs and test in slugs
    assert theirs not in _slugs(client, world['tester'], '?region=north-america&limit=50')


def test_a_testers_gathering_page_is_not_found_for_members_and_visitors(client, world, published):
    test = published(organiser_row=world['tester_org'])
    assert client.get(f'/events/{test}').status_code == 404
    assert client.get(f'/events/{test}', headers=world['member']).status_code == 404
    r = client.get(f'/events/{test}', headers=world['tester'])
    assert r.status_code == 200 and r.get_json()['organiser']['name'] == 'Labs test fellowship'


def test_a_shared_cache_never_keeps_a_signed_in_list(client, world, published):
    published(organiser_row=world['tester_org'])
    anonymous = client.get('/events?limit=50')
    assert anonymous.headers['Cache-Control'] == 'public, max-age=60'
    assert 'Authorization' in anonymous.headers['Vary']
    for who in ('member', 'tester'):
        assert client.get('/events?limit=50', headers=world[who]).headers['Cache-Control'] == 'private, no-store'


def test_an_organiser_under_a_testers_address_is_a_testers(client, world, make_person, published):
    """An organiser made from the public host form under a tester's own
    address, with no member named, is a tester's too."""
    tess = make_person(name='GatherTess', gender='Woman')
    _grant_tester(tess)
    with api_tx() as tx:
        email = tx.execute('SELECT normalized_email FROM person WHERE id = %(i)s',
                           dict(i=tess['id'])).fetchone()['normalized_email']
        oid = tx.execute(
            """INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at)
               VALUES ('Tess hosts', 'other', %(e)s, %(e)s, NOW(), NOW()) RETURNING id""",
            dict(e=email)).fetchone()['id']
    try:
        test = published(organiser_row=dict(id=oid))
        assert test not in _slugs(client)
        assert test not in _slugs(client, world['member'])
        assert test in _slugs(client, world['tester'])
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM organiser WHERE id = %(i)s', dict(i=oid))


def test_members_and_visitors_cannot_rsvp_to_a_testers_gathering(client, world, published, mail_allowed):
    test = published(organiser_row=world['tester_org'])
    body = dict(name='Hannah', email='hannah-gather@ahavah-test.invalid', party_size=1,
                share_email=False, news=False)
    assert client.post(f'/events/{test}/rsvp', json=body).status_code == 404
    assert client.post(f'/events/{test}/rsvp', json=body, headers=world['member']).status_code == 404
    r = client.post(f'/events/{test}/rsvp', json=body, headers=world['tester'])
    assert r.status_code == 201 and r.get_json()['state'] == 'confirmed'
    with api_tx('read committed') as tx:
        guests = tx.execute(
            """SELECT r.person_id FROM event_rsvp r JOIN event e ON e.id = r.event_id
                WHERE e.slug = %(s)s""", dict(s=test)).fetchall()
    assert [g['person_id'] for g in guests] == [world['tobit']['id']]


def test_only_a_testers_view_of_a_testers_gathering_is_counted(client, world, published):
    test = published(organiser_row=world['tester_org'])
    client.post(f'/events/{test}/view', json={'share': 'host'})
    client.post(f'/events/{test}/view', headers=world['member'])
    with api_tx('read committed') as tx:
        def views():
            return tx.execute(
                """SELECT COALESCE(SUM(v.views), 0)::int AS n FROM event_view_day v
                     JOIN event e ON e.id = v.event_id WHERE e.slug = %(s)s""",
                dict(s=test)).fetchone()['n']
        assert views() == 0
    client.post(f'/events/{test}/view', headers=world['tester'])
    with api_tx('read committed') as tx:
        assert tx.execute(
            """SELECT COALESCE(SUM(v.views), 0)::int AS n FROM event_view_day v
                 JOIN event e ON e.id = v.event_id WHERE e.slug = %(s)s""",
            dict(s=test)).fetchone()['n'] == 1


def test_member_emails_never_list_a_testers_gathering(world, published):
    from service.events import public
    test_online = published(organiser_row=world['tester_org'], mode='online', city=None, country=None,
                            region='online', online_url='https://meet.example.com/t',
                            starts_at=datetime.now(timezone.utc) + timedelta(days=3))
    test_dallas = published(organiser_row=world['tester_org'])
    now = datetime.now(timezone.utc)
    with api_tx('read committed') as tx:
        lists = public.gatherings_for_members(tx, now=now, limit=50)
        listed = {c['slug'] for k, cards in lists.items() if k != public.IN_PERSON for c in cards}
        assert test_online not in listed and test_dallas not in listed

    class _Undo(Exception):
        pass

    # With every other online gathering paused, inside a transaction that
    # is rolled back, the tester's is the only one: the welcome still does
    # not promise an online gathering because of it.
    with pytest.raises(_Undo):
        with api_tx() as tx:
            tx.execute("UPDATE event SET paused_at = NOW() WHERE region = 'online' "
                       "AND paused_at IS NULL AND organiser_id <> %(o)s",
                       dict(o=world['tester_org']['id']))
            assert public.online_listed(tx, now=now) is False
            raise _Undo


def test_a_testers_gathering_queues_no_social_post(client, world, event_cleanup):
    from service.events import manage
    from tests.test_event_manage import draft
    for org, posts in ((world['tester_org'], 0), (world['member_org'], 2)):
        r = client.post('/organiser/events', headers=org['headers'], json=draft())
        slug = r.get_json()['slug']
        event_cleanup(slug)
        assert client.post(f'/organiser/events/{slug}/publish', headers=org['headers']).get_json() == {
            'status': 'published'}
        with api_tx('read committed') as tx:
            n = tx.execute(
                """SELECT COUNT(DISTINCT request_key)::int AS n FROM publishing_queue
                    WHERE request_key LIKE %(p)s AND status <> 'cancelled'""",
                dict(p=f'event:{slug}:%')).fetchone()['n']
        assert n == posts, (org['id'], n)
    # The admin's resume and approval both queue through the same function.
    with api_tx() as tx:
        row = tx.execute('SELECT * FROM event WHERE organiser_id = %(o)s',
                         dict(o=world['tester_org']['id'])).fetchone()
        assert manage._queue_posts(tx, dict(row), datetime.now(timezone.utc)) == []


def test_staff_see_a_testers_gathering_labelled_in_admin_events(world, published):
    from service.events import admin
    test = published(organiser_row=world['tester_org'])
    theirs = published(organiser_row=world['member_org'])
    waiting = published(organiser_row=world['tester_org'], status='pending', published_at=None)
    with api_tx('read committed') as tx:
        out = admin.overview(tx)
    flags = {e['slug']: e['test'] for e in out['events']}
    assert flags[test] is True and flags[theirs] is False
    assert {e['slug']: e['test'] for e in out['waiting']['events']}[waiting] is True
    orgs = {o['id']: o['test'] for o in out['organisers']}
    assert orgs[world['tester_org']['id']] is True and orgs[world['member_org']['id']] is False


def test_revoking_the_role_brings_the_gathering_back(client, world, published):
    test = published(organiser_row=world['tester_org'])
    assert test not in _slugs(client)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY[]::TEXT[] WHERE id = %(i)s",
                   dict(i=world['tobit']['id']))
    forget_tester_emails()
    assert test in _slugs(client)
    assert client.get(f'/events/{test}').status_code == 200


def test_feast_labels_are_the_biblical_english_names():
    from service.events.fields import FEASTS
    assert FEASTS['pentecost'] == 'Feast of Weeks'
    assert FEASTS['tabernacles'] == 'Feast of Tabernacles'


def test_a_members_old_place_on_a_testers_gathering_is_hidden_not_deleted(client, world, published,
                                                                            confirmed_guest, monkeypatch):
    """A place a member took before this rule stays in the table but out of
    their list, as every cross like and match is (TEC-2135)."""
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    test = published(organiser_row=world['tester_org'])
    theirs = published(organiser_row=world['member_org'])
    for slug in (test, theirs):
        confirmed_guest(slug, person_id=world['asher']['id'])
    mine = client.get('/rsvp/mine', headers=world['member']).get_json()
    shown = [p['gathering']['slug'] for p in mine['upcoming'] + mine['past']]
    assert theirs in shown and test not in shown
    with api_tx('read committed') as tx:
        assert tx.execute(
            """SELECT COUNT(*)::int AS n FROM event_rsvp r JOIN event e ON e.id = r.event_id
                WHERE e.slug = %(s)s AND r.person_id = %(p)s""",
            dict(s=test, p=world['asher']['id'])).fetchone()['n'] == 1


def _live_posts(slug):
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT COUNT(DISTINCT request_key)::int AS n FROM publishing_queue
                WHERE request_key LIKE %(p)s AND status <> 'cancelled'""",
            dict(p=f'event:{slug}:%')).fetchone()['n']


def test_making_a_host_a_tester_cancels_their_queued_posts(client, world, make_person, sign_in,
                                                          admin_headers, event_cleanup):
    """Posts queued while the host was a member stop when an admin grants
    the role, and the publish worker's last check refuses any that remain."""
    from service.spotlight.growthposts import is_tester_event_post
    from tests.test_event_manage import draft
    ruth = make_person(name='GatherRuth', gender='Woman')
    org = world['member_org']
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET member_person_id = %(p)s WHERE id = %(o)s',
                   dict(p=ruth['id'], o=org['id']))
        uuid = tx.execute('SELECT uuid::text AS u FROM person WHERE id = %(i)s',
                          dict(i=ruth['id'])).fetchone()['u']
    slug = client.post('/organiser/events', headers=org['headers'], json=draft()).get_json()['slug']
    event_cleanup(slug)
    client.post(f'/organiser/events/{slug}/publish', headers=org['headers'])
    assert _live_posts(slug) == 2
    with api_tx('read committed') as tx:
        assert not is_tester_event_post(tx, f'event:{slug}:20990101:d2')
    r = client.patch(f'/admin/users/{uuid}/roles', headers=admin_headers,
                     json=dict(add=['tester'], remove=[], reason='Labs test account'))
    assert r.status_code == 200, r.get_data(as_text=True)
    forget_tester_emails()
    assert _live_posts(slug) == 0
    with api_tx('read committed') as tx:
        assert is_tester_event_post(tx, f'event:{slug}:20990101:d2')
        assert not is_tester_event_post(tx, 'event:no-such-gathering:20990101:d2')


def test_the_publish_worker_checks_for_a_testers_gathering():
    """dispatch_check refuses an event post of a tester's gathering before
    anything reaches Meta (read from the source: building a claimed,
    rendered event row needs the whole render pipeline)."""
    import inspect

    from service.spotlight import dispatch
    src = inspect.getsource(dispatch.dispatch_check)
    assert "is_tester_event_post(tx, row['request_key'])" in src and "'tester_event'" in src
    assert 'tester_event' in dispatch.REASONS


def test_a_testers_gathering_reminds_its_testers_only(world, published, confirmed_guest, monkeypatch):
    """A place a member took before the gathering was hidden gets no
    reminder; a tester's does."""
    from service.events import jobs, mail
    test = published(organiser_row=world['tester_org'])
    member_place = confirmed_guest(test, person_id=world['asher']['id'])
    tester_place = confirmed_guest(test, person_id=world['tobit']['id'])
    reminded = []
    monkeypatch.setattr(jobs, '_reminder_due', lambda *a: True)
    monkeypatch.setattr(jobs.restdays, 'is_rest_period', lambda now: False)
    monkeypatch.setattr(mail, 'reminder_already', lambda tx, rid, starts: False)
    monkeypatch.setattr(mail, '_guest_to', lambda tx, r: 'someone@ahavah-test.invalid')
    monkeypatch.setattr(mail, 'queue_reminder', lambda tx, rid, token: reminded.append(rid) or 1)
    with api_tx() as tx:
        start = tx.execute('SELECT starts_at FROM event WHERE slug = %(s)s', dict(s=test)).fetchone()['starts_at']
        jobs.queue_reminders(tx, start - timedelta(hours=20))
    assert tester_place['id'] in reminded and member_place['id'] not in reminded
