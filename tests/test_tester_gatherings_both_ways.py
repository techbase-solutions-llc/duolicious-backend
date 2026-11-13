"""Testers and members never reach each other's gatherings, both ways
(TEC-2085, decision 3 as decided on 13 Nov 2026; the owner's ruling of 6
Nov, TEC-2135).

tests/test_tester_gatherings.py covers the first way: a tester's gathering
never reaches a member or a signed-out visitor. This module covers the
second, and the places held across the line in either direction:

- A tester never finds a member's gathering: not on /events, its page (the
  same not found as a missing one), the RSVP (the same not found), a view
  count, the welcome's online line, or any email, reminder or push.
- A place across the line (a tester's on a member's gathering, a member's
  or a visitor's on a tester's) is hidden, not deleted: it takes no
  capacity, is in no going count, and its emailed link, Your Ahavah, Your
  gatherings and the organiser's guest list do not show it.
- Signed-out visitors and members are unaffected; staff still see every
  place in Admin > Events; revoking the role brings a place back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.testers import forget_tester_emails
from tests.test_tester_gatherings import _slugs, world  # noqa: F401  (world is a fixture)

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')

_BODY = dict(name='Guest', email='guest-both-ways@ahavah-test.invalid', party_size=1,
             share_email=False, news=False)


def _address(person) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT normalized_email FROM person WHERE id = %(i)s',
                          dict(i=person['id'])).fetchone()['normalized_email']


def _places(slug) -> int:
    """Every RSVP row the gathering has, hidden or not: nothing is deleted."""
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT COUNT(*)::int AS n FROM event_rsvp r JOIN event e ON e.id = r.event_id
                WHERE e.slug = %(s)s""", dict(s=slug)).fetchone()['n']


def _event_id(slug) -> int:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()['id']


# ---------------------------------------------------------------------------
# A tester never finds a member's gathering
# ---------------------------------------------------------------------------

def test_a_members_gathering_page_is_not_found_for_a_tester(client, world, published):
    theirs = published(organiser_row=world['member_org'])
    missing = client.get('/events/no-such-gathering-both-ways', headers=world['tester'])
    r = client.get(f'/events/{theirs}', headers=world['tester'])
    assert r.status_code == 404 and r.get_json() == missing.get_json()
    # Members and signed-out visitors find it as before.
    assert client.get(f'/events/{theirs}').status_code == 200
    assert client.get(f'/events/{theirs}', headers=world['member']).status_code == 200
    assert theirs in _slugs(client) and theirs in _slugs(client, world['member'])


def test_a_tester_cannot_rsvp_to_a_members_gathering(client, world, published, mail_allowed):
    theirs = published(organiser_row=world['member_org'])
    missing = client.post('/events/no-such-gathering-both-ways/rsvp', json=_BODY, headers=world['tester'])
    assert missing.status_code == 404
    r = client.post(f'/events/{theirs}/rsvp', json=_BODY, headers=world['tester'])
    assert r.status_code == 404 and r.get_json() == missing.get_json()
    # Signed out under the tester's own address: the same answer, nothing
    # written.
    r = client.post(f'/events/{theirs}/rsvp', json=dict(_BODY, email=_address(world['tobit'])))
    assert r.status_code == 404 and r.get_json() == missing.get_json()
    assert _places(theirs) == 0
    # A member and a visitor RSVP as before.
    assert client.post(f'/events/{theirs}/rsvp', json=_BODY, headers=world['member']).status_code == 201
    r = client.post(f'/events/{theirs}/rsvp', json=dict(_BODY, email='visitor-both-ways@ahavah-test.invalid'))
    assert r.status_code == 201 and r.get_json()['state'] == 'check_email'
    assert _places(theirs) == 2


def test_a_testers_view_of_a_members_gathering_is_not_counted(client, world, published):
    theirs = published(organiser_row=world['member_org'])

    def views():
        with api_tx('read committed') as tx:
            return tx.execute(
                """SELECT COALESCE(SUM(v.views), 0)::int AS n FROM event_view_day v
                     JOIN event e ON e.id = v.event_id WHERE e.slug = %(s)s""",
                dict(s=theirs)).fetchone()['n']
    client.post(f'/events/{theirs}/view', headers=world['tester'])
    assert views() == 0
    client.post(f'/events/{theirs}/view', headers=world['member'])
    client.post(f'/events/{theirs}/view')
    assert views() == 2


def test_the_welcome_offers_online_gatherings_from_the_readers_side(world, published):
    from service.events import public
    now = datetime.now(timezone.utc)
    online = dict(mode='online', city=None, country=None, region='online',
                  online_url='https://meet.example.com/both-ways', starts_at=now + timedelta(days=3))
    theirs = published(organiser_row=world['member_org'], **online)
    test = published(organiser_row=world['tester_org'], **online)

    class _Undo(Exception):
        pass

    # Inside a transaction that is rolled back, only one side's online
    # gathering is left at a time.
    for keep, member_sees, tester_sees in ((theirs, True, False), (test, False, True)):
        with pytest.raises(_Undo):
            with api_tx() as tx:
                tx.execute("UPDATE event SET paused_at = NOW() WHERE region = 'online' "
                           "AND paused_at IS NULL AND slug <> %(s)s", dict(s=keep))
                assert public.online_listed(tx, now=now) is member_sees
                assert public.online_listed(tx, now=now, viewer_tester=True) is tester_sees
                raise _Undo
    # The welcome asks for the reader's own side (read from the source:
    # sending it needs a whole onboarded member).
    import inspect

    from emails import member_welcome
    assert "viewer_tester=is_tester(tx, row['id'])" in inspect.getsource(member_welcome)


# ---------------------------------------------------------------------------
# A place across the line takes no capacity and is in no count
# ---------------------------------------------------------------------------

def test_a_testers_place_never_fills_a_members_gathering(client, world, published, confirmed_guest):
    theirs = published(organiser_row=world['member_org'], capacity=3, show_going=True)
    # Held before the rule: one by the tester's account, one booked signed
    # out under the tester's address with no account linked.
    confirmed_guest(theirs, person_id=world['tobit']['id'], party_size=2)
    confirmed_guest(theirs, email=_address(world['tobit']), party_size=1)
    for headers in (None, world['member']):
        view = client.get(f'/events/{theirs}', headers=headers or {}).get_json()
        assert (view['going'], view['places_left'], view['state']) == (0, 3, 'open')
    assert [c['going'] for c in client.get('/events?limit=50').get_json()['events']
            if c['slug'] == theirs] == [0]
    # The member takes the 3 places the tester's would otherwise fill.
    r = client.post(f'/events/{theirs}/rsvp', json=dict(_BODY, party_size=3), headers=world['member'])
    assert r.status_code == 201, r.get_json()
    view = client.get(f'/events/{theirs}').get_json()
    assert (view['going'], view['places_left'], view['state']) == (3, 0, 'full')
    assert _places(theirs) == 3


def test_a_members_place_never_fills_a_testers_gathering(client, world, published, confirmed_guest):
    test = published(organiser_row=world['tester_org'], capacity=2, show_going=True)
    confirmed_guest(test, person_id=world['asher']['id'], party_size=2)
    confirmed_guest(test, party_size=1)  # a visitor's, from before the gathering was hidden
    view = client.get(f'/events/{test}', headers=world['tester']).get_json()
    assert (view['going'], view['places_left'], view['state']) == (0, 2, 'open')
    r = client.post(f'/events/{test}/rsvp', json=dict(_BODY, party_size=2), headers=world['tester'])
    assert r.status_code == 201, r.get_json()
    assert client.get(f'/events/{test}', headers=world['tester']).get_json()['going'] == 2
    assert _places(test) == 3


def test_revoking_the_role_brings_a_testers_place_back(client, world, published, confirmed_guest):
    theirs = published(organiser_row=world['member_org'], show_going=True)
    confirmed_guest(theirs, person_id=world['tobit']['id'], party_size=2)
    assert client.get(f'/events/{theirs}').get_json()['going'] == 0
    with api_tx() as tx:
        tx.execute('UPDATE person SET roles = ARRAY[]::TEXT[] WHERE id = %(i)s', dict(i=world['tobit']['id']))
    forget_tester_emails()
    assert client.get(f'/events/{theirs}').get_json()['going'] == 2


# ---------------------------------------------------------------------------
# A place across the line is hidden from its link and every list
# ---------------------------------------------------------------------------

def test_a_members_place_on_an_ended_testers_gathering_is_hidden(client, world, published,
                                                                 confirmed_guest, monkeypatch):
    """The case found on production on 13 Nov 2026: a member holds a place
    on a tester's gathering that ended today. Its emailed link and the
    address's Your Ahavah page no longer show it; the row stays."""
    from service import your_ahavah
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    now = datetime.now(timezone.utc)
    ended = dict(starts_at=now - timedelta(hours=4), ends_at=now - timedelta(hours=1))
    test = published(organiser_row=world['tester_org'], **ended)
    theirs = published(organiser_row=world['member_org'], **ended)
    ne = _address(world['asher'])
    hidden = confirmed_guest(test, email=ne, person_id=world['asher']['id'])
    kept = confirmed_guest(theirs, email=ne, person_id=world['asher']['id'])
    assert client.get(f"/rsvp/{hidden['token']}").status_code == 404
    assert client.get(f"/rsvp/{hidden['token']}/calendar.ics").status_code == 404
    assert client.post(f"/rsvp/{hidden['token']}/cancel").status_code == 404
    assert client.get(f"/rsvp/{kept['token']}").status_code == 200
    with api_tx('read committed') as tx:
        shown = [p['slug'] for p in your_ahavah.held(tx, ne)['places']]
    assert theirs in shown and test not in shown
    mine = client.get('/rsvp/mine', headers=world['member']).get_json()
    assert [p['gathering']['slug'] for p in mine['upcoming'] + mine['past']] == [theirs]
    assert client.get(f"/rsvp/mine/{hidden['id']}", headers=world['member']).status_code == 404
    assert _places(test) == 1


def test_a_testers_place_on_a_members_gathering_is_hidden_from_the_tester(client, world, published,
                                                                          confirmed_guest, monkeypatch):
    from service import your_ahavah
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    theirs = published(organiser_row=world['member_org'])
    test = published(organiser_row=world['tester_org'])
    ne = _address(world['tobit'])
    hidden = confirmed_guest(theirs, email=ne, person_id=world['tobit']['id'])
    kept = confirmed_guest(test, email=ne, person_id=world['tobit']['id'])
    assert client.get(f"/rsvp/{hidden['token']}").status_code == 404
    assert client.get(f"/rsvp/{kept['token']}").status_code == 200
    mine = client.get('/rsvp/mine', headers=world['tester']).get_json()
    assert [p['gathering']['slug'] for p in mine['upcoming'] + mine['past']] == [test]
    for path in (f"/rsvp/mine/{hidden['id']}", f"/rsvp/mine/{hidden['id']}/calendar.ics"):
        assert client.get(path, headers=world['tester']).status_code == 404
    assert client.post(f"/rsvp/mine/{hidden['id']}/cancel", headers=world['tester']).status_code == 404
    with api_tx('read committed') as tx:
        assert [p['slug'] for p in your_ahavah.held(tx, ne)['places']] == [test]
        assert tx.execute('SELECT status FROM event_rsvp WHERE id = %(i)s',
                          dict(i=hidden['id'])).fetchone()['status'] == 'going'


def test_the_organiser_never_sees_a_place_across_the_line(client, world, published, confirmed_guest):
    from service import your_ahavah
    theirs = published(organiser_row=world['member_org'])
    test = published(organiser_row=world['tester_org'])
    # On the member's gathering: a visitor's place, and one booked signed
    # out under the tester's address (no account linked).
    confirmed_guest(theirs, name='Visitor Vashti')
    confirmed_guest(theirs, name='Tester by address', email=_address(world['tobit']))
    # On the tester's gathering: a visitor's place, and the tester's own.
    confirmed_guest(test, name='Visitor Zillah')
    confirmed_guest(test, name='Tester Tobit', person_id=world['tobit']['id'])
    for org, slug, name in ((world['member_org'], theirs, 'Visitor Vashti'),
                            (world['tester_org'], test, 'Tester Tobit')):
        out = client.get(f'/organiser/events/{slug}/rsvps', headers=org['headers']).get_json()
        assert [g['name'] for g in out['going']] == [name] and out['total_going'] == 1
        mine = client.get('/organiser/me', headers=org['headers']).get_json()
        assert [e['going'] for e in mine['groups']['published'] if e['slug'] == slug] == [1]
        with api_tx('read committed') as tx:
            hosting = your_ahavah.held(tx, org['email'].lower())['hosting']
        assert [h['going'] for h in hosting if h['slug'] == slug] == [1]


def test_an_organiser_under_a_testers_address_sees_its_testers(client, world, published, confirmed_guest):
    """An organiser with no member account, under a tester's address, is a
    tester's: its guest list, count and digest hold its testers' places and
    no one else's."""
    from datetime import date

    from service.events import mail
    org = world['tester_org']
    address = 'tobit-host-both-ways@ahavah-test.invalid'  # a mailable address, for the digest
    with api_tx() as tx:
        tx.execute('UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s',
                   dict(e=address, i=world['tobit']['id']))
        tx.execute('UPDATE organiser SET member_person_id = NULL, email = %(e)s, normalized_email = %(e)s '
                   'WHERE id = %(o)s', dict(e=address, o=org['id']))
    test = published(organiser_row=org)
    confirmed_guest(test, name='Visitor Zillah')
    confirmed_guest(test, name='Member Asher', person_id=world['asher']['id'])
    confirmed_guest(test, name='Tester Tobit', person_id=world['tobit']['id'], party_size=2)
    out = client.get(f'/organiser/events/{test}/rsvps', headers=org['headers']).get_json()
    assert [g['name'] for g in out['going']] == ['Tester Tobit'] and out['total_going'] == 2
    eid = _event_id(test)
    with api_tx() as tx:
        assert mail.queue_digest(tx, eid, date.today()) is not None
    with api_tx('read committed') as tx:
        [row] = tx.execute("SELECT payload FROM email_outbox WHERE campaign = 'event_digest' "
                           "AND organiser_id = %(o)s", dict(o=org['id'])).fetchall()
    body = row['payload']['html']
    assert 'Tester Tobit' in body and 'Visitor Zillah' not in body and 'Member Asher' not in body


def test_a_visitor_confirms_by_link_past_a_testers_place(client, world, published, confirmed_guest,
                                                        mail_allowed, monkeypatch):
    """A tester's place takes no capacity when a visitor's emailed link
    confirms theirs, as when they first asked."""
    from service.events import mail
    theirs = published(organiser_row=world['member_org'], capacity=1)
    confirmed_guest(theirs, person_id=world['tobit']['id'])
    tokens = []
    monkeypatch.setattr(mail, 'queue_confirm', lambda tx, rid, token: tokens.append(token))
    r = client.post(f'/events/{theirs}/rsvp', json=dict(_BODY, email='visitor-cap@ahavah-test.invalid'))
    assert r.status_code == 201 and len(tokens) == 1
    r = client.get(f'/rsvp/confirm/{tokens[0]}')
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['rsvp']['confirmed'] is True
    assert client.get(f'/events/{theirs}').get_json()['places_left'] == 0


def test_a_queued_join_invite_for_a_place_across_the_line_is_withdrawn(world, published, confirmed_guest):
    """The outbox reads the place again at the send: a visitor's place on a
    tester's gathering is hidden, so its invitation goes nowhere."""
    from service.campaigns import outbox
    p = _four_places(world, published, confirmed_guest)
    with api_tx('read committed') as tx:
        def place(rid):
            row = tx.execute('SELECT event_id, lead_id FROM event_rsvp WHERE id = %(i)s', dict(i=rid)).fetchone()
            return tx.execute(outbox._Q_JOIN_INVITE_RSVP, dict(e=row['event_id'], l=row['lead_id'])).fetchone()
        assert place(p['v_on_m']) is not None
        assert place(p['v_on_t']) is None


def test_staff_still_see_every_place_in_admin_events(world, published, confirmed_guest):
    from service.events import admin
    theirs = published(organiser_row=world['member_org'])
    confirmed_guest(theirs, person_id=world['asher']['id'])
    confirmed_guest(theirs, person_id=world['tobit']['id'])
    with api_tx('read committed') as tx:
        row = next(e for e in admin.overview(tx)['events'] if e['slug'] == theirs)
    assert row['rsvps'] == 2 and row['test'] is False


# ---------------------------------------------------------------------------
# Emails, reminders and pushes
# ---------------------------------------------------------------------------

def _four_places(world, published, confirmed_guest, **over):
    """A member's and a tester's gathering, each with a member's and a
    tester's place, and a visitor's place on each."""
    theirs = published(organiser_row=world['member_org'], **over)
    test = published(organiser_row=world['tester_org'], **over)
    a, t = world['asher']['id'], world['tobit']['id']
    return dict(
        theirs=theirs, test=test,
        m_on_m=confirmed_guest(theirs, person_id=a)['id'], t_on_m=confirmed_guest(theirs, person_id=t)['id'],
        v_on_m=confirmed_guest(theirs)['id'],
        m_on_t=confirmed_guest(test, person_id=a)['id'], t_on_t=confirmed_guest(test, person_id=t)['id'],
        v_on_t=confirmed_guest(test)['id'])


def test_change_and_cancel_emails_skip_places_across_the_line(world, published, confirmed_guest):
    from service.events import mail
    p = _four_places(world, published, confirmed_guest)
    # api_tx is one shared connection, not re-entrant: read the ids first.
    ids = {k: _event_id(p[k]) for k in ('theirs', 'test')}
    with api_tx('read committed') as tx:
        def guests(key):
            return {r['id'] for r in mail._confirmed_guests(tx, ids[key])}
        assert guests('theirs') == {p['m_on_m'], p['v_on_m']}
        assert guests('test') == {p['t_on_t']}
        for across in ('t_on_m', 'm_on_t', 'v_on_t'):
            assert mail._rsvp_row(tx, p[across]) is None, across
        for same in ('m_on_m', 'v_on_m', 't_on_t'):
            assert mail._rsvp_row(tx, p[same]) is not None, same


def test_reminders_go_to_places_on_the_gatherings_side_only(world, published, confirmed_guest, monkeypatch):
    from service.events import jobs, mail
    p = _four_places(world, published, confirmed_guest)
    reminded = []
    monkeypatch.setattr(jobs, '_reminder_due', lambda *a: True)
    monkeypatch.setattr(jobs.restdays, 'is_rest_period', lambda now: False)
    monkeypatch.setattr(mail, 'reminder_already', lambda tx, rid, starts: False)
    # The fixture's people have @example.com addresses, which are never mailed.
    monkeypatch.setattr(mail, '_guest_to', lambda tx, r: 'someone@ahavah-test.invalid')
    monkeypatch.setattr(mail, 'queue_reminder', lambda tx, rid, token: reminded.append(rid) or 1)
    with api_tx() as tx:
        start = tx.execute('SELECT starts_at FROM event WHERE slug = %(s)s',
                           dict(s=p['theirs'])).fetchone()['starts_at']
        jobs.queue_reminders(tx, start - timedelta(hours=20))
    mine = {p[k] for k in ('m_on_m', 't_on_m', 'v_on_m', 'm_on_t', 't_on_t', 'v_on_t')}
    assert set(reminded) & mine == {p['m_on_m'], p['v_on_m'], p['t_on_t']}


@pytest.mark.usefixtures('release_4_schema')
def test_reminder_pushes_go_to_places_on_the_gatherings_side_only(world, published, confirmed_guest):
    from uuid import uuid4

    from service.events.jobs import _REMINDER_LOOKAHEAD
    from service.notifications import activity_pushes as ap
    now = datetime.now(timezone.utc)
    p = _four_places(world, published, confirmed_guest, starts_at=now + timedelta(hours=20))
    with api_tx() as tx:
        for who in ('asher', 'tobit'):
            # The push audience leaves out the fixture's @example.com addresses.
            address = f'{who}-{uuid4().hex[:8]}@ahavah-test.invalid'
            tx.execute('UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s',
                       dict(e=address, i=world[who]['id']))
            tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                          VALUES (%(i)s, %(e)s, 'k', 'a', 'UTC')""",
                       dict(i=world[who]['id'], e=f'https://push.test/{uuid4()}'))
        rows = tx.execute(ap._Q_GOING_SOON, ap._params(now=now, until=now + _REMINDER_LOOKAHEAD)).fetchall()
        # The new-guests push reads with the same rule; it must still run.
        tx.execute(ap._Q_NEW_GUESTS, ap._params(now=now, since=now - timedelta(days=1))).fetchall()
    ours = {p[k] for k in ('m_on_m', 't_on_m', 'm_on_t', 't_on_t')}
    assert {r['rsvp_id'] for r in rows} & ours == {p['m_on_m'], p['t_on_t']}


def test_join_invites_skip_a_visitors_place_on_a_testers_gathering(world, published, confirmed_guest,
                                                                   monkeypatch):
    from service.events import jobs, join, mail
    now = datetime.now(timezone.utc)
    ended = dict(starts_at=now - timedelta(hours=4), ends_at=now - timedelta(hours=1))
    p = _four_places(world, published, confirmed_guest, **ended)
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET marketing_consent = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[p['v_on_m'], p['v_on_t']]))
    asked = []
    monkeypatch.setattr('service.events.switch_on', lambda key: True)
    monkeypatch.setattr(join, 'invite_due', lambda *a: True)
    monkeypatch.setattr(mail, 'queue_join_invite', lambda tx, r, ev, now: asked.append(r['id']) or 1)
    with api_tx() as tx:
        jobs.queue_join_invites(tx, now)
    assert p['v_on_m'] in asked and p['v_on_t'] not in asked
