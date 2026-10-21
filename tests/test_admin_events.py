"""Admin > Events (TEC-1845): approvals, pausing, the badge, the figures
(counts only, never a guest's name or email) and the leaders' invite
requests, with POST /invite-ahavah."""
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')


def _row(slug):
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone())


def _post_statuses(slug):
    with api_tx('read committed') as tx:
        rows = tx.execute(
            """SELECT status, COUNT(DISTINCT request_key)::int AS n FROM publishing_queue
                WHERE request_key LIKE %(p)s GROUP BY status""", dict(p=f'event:{slug}:%')).fetchall()
    return {r['status']: r['n'] for r in rows}


def _organiser_rows(campaign, organiser_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM email_outbox WHERE campaign = %(c)s AND organiser_id = %(o)s ORDER BY id',
            dict(c=campaign, o=organiser_id)).fetchall()]


@pytest.fixture
def create(client, event_cleanup):
    from tests.test_event_manage import draft

    def _create(o, **over):
        slug = client.post('/organiser/events', headers=o['headers'], json=draft(**over)).get_json()['slug']
        event_cleanup(slug)
        return slug
    return _create


def _event(body, slug):
    return next(e for e in body['events'] if e['slug'] == slug)


def test_the_overview_counts_without_names(client, admin_headers, published, confirmed_guest):
    slug = published()
    confirmed_guest(slug, name='Hannah Okafor', email='hannah@ahavah-test.invalid')
    body = client.get('/admin/events', headers=admin_headers).get_data(as_text=True)
    assert 'Hannah' not in body and 'hannah@' not in body
    row = _event(client.get('/admin/events', headers=admin_headers).get_json(), slug)
    assert (row['rsvps'], row['confirmed']) == (1, 1)


def test_the_overview_counts_views_attendance_and_new_addresses(client, admin_headers, published, confirmed_guest):
    slug = published()
    g = confirmed_guest(slug)
    client.post(f'/events/{slug}/view')
    client.post(f'/events/{slug}/rsvp', json=dict(name='New', email='brand-new-x@ahavah-test.invalid', party_size=1))
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET attended_at = NOW() WHERE id = %(i)s', dict(i=g['id']))
    row = _event(client.get('/admin/events', headers=admin_headers).get_json(), slug)
    assert (row['views'], row['rsvps'], row['confirmed'], row['attended'], row['new_addresses']) == (1, 2, 1, 1, 1)
    weeks = client.get(f'/admin/events/{slug}/weeks', headers=admin_headers).get_json()['weeks']
    assert sum(w['views'] for w in weeks) == 1 and sum(w['rsvps'] for w in weeks) == 2


def test_approving_an_organiser_lets_their_next_gathering_publish(client, admin_headers, organiser, create):
    o = organiser(approved=False)
    first = create(o)
    assert client.post(f'/organiser/events/{first}/publish', headers=o['headers']).get_json() == {'status': 'pending'}
    waiting = client.get('/admin/events', headers=admin_headers).get_json()['waiting']
    assert o['id'] in [w['id'] for w in waiting['organisers']]
    assert client.post(f"/admin/events/organisers/{o['id']}/approve", headers=admin_headers, json={}).status_code == 200
    assert _row(first)['status'] == 'pending'  # approval publishes nothing by itself
    [note] = _organiser_rows('event_organiser_note', o['id'])
    assert note['payload']['subject'] == 'Your request to host on Ahavah is approved'
    assert 'Ahavah has approved your request to host.' in note['payload']['html']
    second = create(o)
    assert client.post(f'/organiser/events/{second}/publish', headers=o['headers']).get_json() == {'status': 'published'}


def test_approving_a_pending_gathering_publishes_it_and_queues_its_posts(client, admin_headers, organiser, create):
    o = organiser(approved=False)
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    assert slug in [e['slug'] for e in client.get('/admin/events', headers=admin_headers).get_json()['waiting']['events']]
    assert client.post(f'/admin/events/{slug}/approve', headers=admin_headers).status_code == 200
    row = _row(slug)
    assert (row['status'], row['flag_reason']) == ('published', None) and row['published_at'] is not None
    assert _post_statuses(slug) == {'awaiting_render': 2}
    [note] = _organiser_rows('event_organiser_note', o['id'])
    assert note['payload']['subject'] == 'Marriage preparation evening is live on Ahavah'
    assert client.get(f'/events/{slug}').status_code == 200


def test_declining_a_gathering_returns_it_to_drafts(client, admin_headers, organiser, create):
    o = organiser(approved=False)
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    assert client.post(f'/admin/events/{slug}/decline', headers=admin_headers).status_code == 200
    row = _row(slug)
    assert (row['status'], row['flag_reason']) == ('draft', 'declined')


def test_pausing_hides_the_page_and_cancels_the_posts(client, admin_headers, organiser, create):
    o = organiser()
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    assert client.post(f'/admin/events/{slug}/pause', headers=admin_headers).status_code == 200
    assert client.get(f'/events/{slug}').status_code == 404 and _post_statuses(slug) == {'cancelled': 2}
    assert client.post(f'/admin/events/{slug}/resume', headers=admin_headers).status_code == 200
    assert client.get(f'/events/{slug}').status_code == 200 and _post_statuses(slug) == {'awaiting_render': 2}


def test_a_change_made_while_paused_reaches_the_guests_only_on_resume(
        client, admin_headers, organiser, create, confirmed_guest, monkeypatch):
    from tests.test_event_manage import _iso
    calls = []
    monkeypatch.setattr('service.events.mail.queue_change', lambda tx, eid: calls.append(eid) or 1)
    o = organiser()
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    confirmed_guest(slug)
    client.post(f'/admin/events/{slug}/pause', headers=admin_headers)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'],
                     json=dict(starts_at=_iso(31, 1), ends_at=_iso(31, 4)))
    assert r.get_json()['notified'] == 0 and calls == []
    assert _post_statuses(slug) == {'cancelled': 2}
    assert client.post(f'/admin/events/{slug}/resume', headers=admin_headers).status_code == 200
    assert calls == [_row(slug)['id']]
    assert _post_statuses(slug) == {'cancelled': 2, 'awaiting_render': 2}
    assert 'held' not in _row(slug)['change_after']


def test_a_flagged_change_reaches_the_guests_once_the_admin_approves(
        client, admin_headers, organiser, create, confirmed_guest, monkeypatch):
    from tests.test_event_manage import SCAM, _iso
    calls = []
    monkeypatch.setattr('service.events.mail.queue_change', lambda tx, eid: calls.append(eid) or 1)
    o = organiser()
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    confirmed_guest(slug)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'],
                     json=dict(description=SCAM, starts_at=_iso(31, 1), ends_at=_iso(31, 4)))
    assert r.get_json() == {'event': {'slug': slug, 'status': 'pending'}, 'notified': 0} and calls == []
    assert client.post(f'/admin/events/{slug}/approve', headers=admin_headers).status_code == 200
    assert calls == [_row(slug)['id']]


def test_revoking_an_organiser_pauses_their_gatherings_and_ends_their_links(client, admin_headers, organiser, create):
    o = organiser()
    slug = create(o)
    client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
    assert client.post(f"/admin/events/organisers/{o['id']}/revoke", headers=admin_headers).status_code == 200
    assert _row(slug)['paused_at'] is not None and client.get(f'/events/{slug}').status_code == 404
    assert client.get('/organiser/me', headers=o['headers']).status_code == 401


def test_declining_an_organiser_revokes_them(client, admin_headers, organiser):
    o = organiser(approved=False)
    assert client.post(f"/admin/events/organisers/{o['id']}/decline", headers=admin_headers).status_code == 200
    assert client.get('/organiser/me', headers=o['headers']).status_code == 401


def test_ahavahs_own_organiser_is_created_approved_and_gets_a_link(client, admin_headers):
    r = client.post('/admin/events/organisers', headers=admin_headers,
                    json=dict(name='Ahavah', email='ahavah-own-x@ahavah-test.invalid'))
    assert r.status_code == 201
    oid = r.get_json()['id']
    try:
        [row] = _organiser_rows('event_manage', oid)
        assert '/host/gatherings?t=' in row['payload']['html']
        orgs = {x['id']: x for x in client.get('/admin/events', headers=admin_headers).get_json()['organisers']}
        assert orgs[oid]['kind'] == 'ahavah' and orgs[oid]['approved_at'] is not None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM organiser WHERE id = %(i)s', dict(i=oid))


def test_the_badge_is_set_by_the_admin(client, admin_headers, published):
    slug = published()
    assert client.post(f'/admin/events/{slug}/attending', headers=admin_headers, json=dict(on=True)).status_code == 200
    assert client.get(f'/events/{slug}').get_json()['ahavah_attending'] is True
    client.post(f'/admin/events/{slug}/attending', headers=admin_headers, json=dict(on=False))
    assert client.get(f'/events/{slug}').get_json()['ahavah_attending'] is False


def test_ahavahs_own_gatherings_start_with_the_badge(client, organiser, create):
    o = organiser(kind='ahavah')
    assert _row(create(o))['ahavah_attending'] is True


def test_women_are_counted_among_member_rsvps_only(client, admin_headers, published, make_person, sign_in):
    slug = published()
    for name, gender in (('Ruth', 'Woman'), ('Boaz', 'Man')):
        p = make_person(name=name, gender=gender, email=f'{name.lower()}-ev@ahavah-test.invalid')
        client.post(f'/events/{slug}/rsvp', headers=sign_in(p), json=dict(name=name, party_size=1))
    client.post(f'/events/{slug}/rsvp', json=dict(name='Visitor', email='visitor-w@ahavah-test.invalid', party_size=1))
    row = _event(client.get('/admin/events', headers=admin_headers).get_json(), slug)
    assert (row['member_rsvps'], row['women_members']) == (2, 1)


def test_signups_are_counted_by_their_source(client, admin_headers, published, make_person):
    slug = published()
    p = make_person(name='Joined')
    with api_tx() as tx:
        tx.execute('UPDATE person SET lead_source = %(s)s WHERE id = %(i)s', dict(s=f'event:{slug}', i=p['id']))
    assert _event(client.get('/admin/events', headers=admin_headers).get_json(), slug)['signups'] == 1


@pytest.fixture
def forget_requests():
    yield
    with api_tx() as tx:
        tx.execute("DELETE FROM ahavah_invite_request WHERE contact_email LIKE '%%@ahavah-test.invalid'")


def test_a_leader_asks_ahavah_to_come_and_it_waits_in_the_admin(client, admin_headers, monkeypatch, forget_requests):
    monkeypatch.setenv('AHAVAH_EVENTS_INVITE_ENABLED', '1')
    r = client.post('/invite-ahavah', json=dict(gathering='Sukkot at Lake Lanier', dates='26 to 30 September 2027',
                    place='Georgia, United States', numbers=120, contact_name='Daniel', contact_email='daniel@ahavah-test.invalid'))
    assert r.status_code == 201
    req = client.get('/admin/events', headers=admin_headers).get_json()['requests'][0]
    assert req['status'] == 'new' and req['gathering'] == 'Sukkot at Lake Lanier'
    assert client.patch(f"/admin/events/requests/{req['id']}", headers=admin_headers,
                        json=dict(status='contacted', notes='Called on Monday')).status_code == 200
    req = client.get('/admin/events', headers=admin_headers).get_json()['requests'][0]
    assert (req['status'], req['notes']) == ('contacted', 'Called on Monday')


def test_the_invite_page_is_closed_until_its_switch_and_the_honeypot_stores_nothing(client, monkeypatch, forget_requests):
    body = dict(gathering='G', dates='Soon', place='Here', contact_name='Bot', contact_email='bot-x@ahavah-test.invalid')
    monkeypatch.delenv('AHAVAH_EVENTS_INVITE_ENABLED')
    assert client.post('/invite-ahavah', json=body).status_code == 404
    monkeypatch.setenv('AHAVAH_EVENTS_INVITE_ENABLED', '1')
    assert client.post('/invite-ahavah', json=dict(body, website='http://x.example')).status_code == 201
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM ahavah_invite_request WHERE contact_email = 'bot-x@ahavah-test.invalid'").fetchone() is None
    assert client.post('/invite-ahavah', json=dict(body, contact_email='nope')).status_code == 400


def test_admin_routes_work_while_dark(client, admin_headers, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    assert client.get('/admin/events', headers=admin_headers).status_code == 200


ROUTES = [('get', '/admin/events'), ('get', '/admin/events/x/weeks'), ('post', '/admin/events/organisers'),
          ('post', '/admin/events/organisers/1/approve'), ('post', '/admin/events/organisers/1/decline'),
          ('post', '/admin/events/organisers/1/revoke'), ('post', '/admin/events/x/approve'),
          ('post', '/admin/events/x/decline'), ('post', '/admin/events/x/pause'), ('post', '/admin/events/x/resume'),
          ('post', '/admin/events/x/attending'), ('patch', '/admin/events/requests/1')]


# Valid bodies: as in every admin route, the body is checked before the role.
BODIES = {'/admin/events/organisers': dict(name='X', email='x@ahavah-test.invalid'),
          '/admin/events/x/attending': dict(on=True)}


def test_every_admin_route_needs_an_admin(client, make_person, sign_in):
    headers = sign_in(make_person(name='Member'))
    for method, path in ROUTES:
        r = getattr(client, method)(path, headers=headers, json=BODIES.get(path, {}))
        assert r.status_code == 403, (method, path, r.status_code)


def test_every_change_is_audited(client, admin_headers, organiser, published):
    o = organiser(approved=False)
    slug = published()
    client.post(f"/admin/events/organisers/{o['id']}/approve", headers=admin_headers, json={})
    client.post(f'/admin/events/{slug}/pause', headers=admin_headers)
    client.post(f'/admin/events/{slug}/resume', headers=admin_headers)
    client.post(f'/admin/events/{slug}/attending', headers=admin_headers, json=dict(on=True))
    with api_tx('read committed') as tx:
        actions = [r['action'] for r in tx.execute(
            """SELECT action FROM admin_audit_log WHERE action LIKE 'events.%%'
                 AND (metadata->>'organiser_id' = %(o)s OR metadata->>'slug' = %(s)s) ORDER BY created_at""",
            dict(o=str(o['id']), s=slug)).fetchall()]
    assert actions == ['events.organiser.approve', 'events.event.pause', 'events.event.resume',
                       'events.event.attending']
