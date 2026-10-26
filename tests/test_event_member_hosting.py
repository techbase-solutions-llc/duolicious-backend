"""Hosting from the app (TEC-1845; ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 4, release 3).

A member asks to host with no code for their own address, and with the
usual code for another one; the organiser made under another address names
the member (migration 0080), so the member's session opens it on any device.
Organisers never see which guests are members."""
import hashlib

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')


@pytest.fixture(autouse=True)
def _hosting_and_entries(monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')


@pytest.fixture
def made():
    """Organisers a test made through the routes, deleted afterwards."""
    ids: list[int] = []
    yield ids
    with api_tx() as tx:
        tx.execute('DELETE FROM organiser WHERE id = ANY(%(i)s)', dict(i=ids))


def _member(make_person, sign_in, name='Samuel Brooks'):
    from uuid import uuid4
    p = make_person(name=name, email=f'member-{uuid4().hex[:12]}@ahavah-test.invalid')
    return p, sign_in(p)


def _organiser_of(token: str) -> dict:
    from service.events.organisers import organiser_for
    with api_tx() as tx:
        o = organiser_for(tx, token)
        o['member_person_id'] = tx.execute('SELECT member_person_id FROM organiser WHERE id = %(i)s',
                                           dict(i=o['id'])).fetchone()['member_person_id']
    return o


def _token_of(headers: dict) -> str:
    return headers['Authorization'].split()[1]


BODY = dict(name='Grace Fellowship', kind='assembly', city='Dallas', country='United States')


def test_a_member_hosts_under_their_own_address_with_no_code(client, make_person, sign_in, made):
    p, headers = _member(make_person, sign_in)
    r = client.post('/host-requests', headers=headers, json=BODY)
    assert r.status_code == 201 and r.get_json()['state'] == 'created'
    o = _organiser_of(r.get_json()['token'])
    made.append(o['id'])
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    assert (o['email'], o['member_person_id']) == (email, p['id'])


def test_a_member_hosts_under_another_address_proved_with_the_code(client, make_person, sign_in,
                                                                   tool_visitor, made):
    p, headers = _member(make_person, sign_in)
    church, church_headers = tool_visitor()
    r = client.post('/host-requests', headers=headers,
                    json=dict(BODY, address_token=_token_of(church_headers)))
    assert r.status_code == 201 and r.get_json()['state'] == 'created'
    o = _organiser_of(r.get_json()['token'])
    made.append(o['id'])
    assert (o['email'], o['member_person_id']) == (church, p['id'])
    # The code's session was for this one request: it is gone, and the
    # member's own session still answers.
    h = hashlib.sha512(_token_of(church_headers).encode()).hexdigest()
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE session_token_hash = %(h)s',
                          dict(h=h)).fetchone() is None
    assert client.get('/app-entries/status', headers=headers).status_code == 200


def test_another_address_needs_a_proved_code(client, make_person, sign_in):
    _, headers = _member(make_person, sign_in)
    r = client.post('/host-requests', headers=headers, json=dict(BODY, address_token='x' * 64))
    assert (r.status_code, r.get_json()) == (403, {'error': 'unproven'})


def test_another_address_is_not_taken_while_app_entries_is_off(client, make_person, sign_in,
                                                               tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'off')
    _, headers = _member(make_person, sign_in)
    _, church_headers = tool_visitor()
    r = client.post('/host-requests', headers=headers,
                    json=dict(BODY, address_token=_token_of(church_headers)))
    assert r.status_code == 404


def test_a_member_who_proves_an_address_that_already_hosts_is_linked_to_it(client, make_person, sign_in,
                                                                         tool_visitor, organiser):
    o = organiser()
    p, headers = _member(make_person, sign_in)
    _, church_headers = tool_visitor(o['email'])
    r = client.post('/host-requests', headers=headers,
                    json=dict(BODY, address_token=_token_of(church_headers)))
    assert r.status_code == 201 and r.get_json()['state'] == 'approved'
    assert _organiser_of(r.get_json()['token'])['member_person_id'] == p['id']


def test_the_members_session_opens_every_organiser_it_holds(client, make_person, sign_in, tool_visitor,
                                                            published, made):
    p, headers = _member(make_person, sign_in)
    own = client.post('/host-requests', headers=headers, json=BODY).get_json()
    _, church_headers = tool_visitor()
    church = client.post('/host-requests', headers=headers,
                         json=dict(BODY, name='Grace Fellowship Dallas',
                                   address_token=_token_of(church_headers))).get_json()
    own_o, church_o = _organiser_of(own['token']), _organiser_of(church['token'])
    made.extend([own_o['id'], church_o['id']])
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET approved_at = NOW() WHERE id = %(i)s', dict(i=church_o['id']))
    slug = published(dict(id=church_o['id']))

    r = client.post('/organiser/member', headers=headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body['name'] == 'Samuel Brooks'
    held = body['organisers']
    # The approved one first.
    assert [o['email'] for o in held] == [church_o['email'], own_o['email']]
    assert [o['approved'] for o in held] == [True, False]
    assert [g['slug'] for g in held[0]['groups']['published']] == [slug]
    # Each comes with a link that opens it, as the emailed one does.
    me = client.get('/organiser/me', headers={'X-Organiser-Token': held[0]['token']}).get_json()
    assert me['email'] == church_o['email']


def test_another_members_session_opens_nothing(client, make_person, sign_in, made):
    _, headers = _member(make_person, sign_in)
    out = client.post('/host-requests', headers=headers, json=BODY).get_json()
    made.append(_organiser_of(out['token'])['id'])
    _, other = _member(make_person, sign_in, name='Ruth')
    r = client.post('/organiser/member', headers=other)
    assert r.status_code == 200 and r.get_json()['organisers'] == []


def test_a_refused_organiser_is_not_opened(client, make_person, sign_in, made):
    _, headers = _member(make_person, sign_in)
    out = client.post('/host-requests', headers=headers, json=BODY).get_json()
    oid = _organiser_of(out['token'])['id']
    made.append(oid)
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET revoked_at = NOW() WHERE id = %(i)s', dict(i=oid))
    assert client.post('/organiser/member', headers=headers).get_json()['organisers'] == []
    again = client.post('/host-requests', headers=headers, json=BODY)
    assert (again.status_code, again.get_json()) == (403, {'error': 'revoked'})


@pytest.mark.parametrize('off', ['AHAVAH_APP_ENTRIES', 'AHAVAH_EVENTS_HOSTING_ENABLED'])
def test_the_members_organisers_follow_hosting_and_app_entries(client, make_person, sign_in, monkeypatch, off):
    monkeypatch.delenv(off)
    _, headers = _member(make_person, sign_in)
    assert client.post('/organiser/member', headers=headers).status_code == 404


def test_a_visitor_has_no_member_organisers(client, tool_visitor):
    _, headers = tool_visitor()
    assert client.post('/organiser/member', headers=headers).status_code == 401


def test_the_guest_list_never_says_who_is_a_member(client, make_person, sign_in, published, made):
    p, headers = _member(make_person, sign_in)
    out = client.post('/host-requests', headers=headers, json=BODY).get_json()
    o = _organiser_of(out['token'])
    made.append(o['id'])
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET approved_at = NOW() WHERE id = %(i)s', dict(i=o['id']))
    slug = published(dict(id=o['id']))
    guest, guest_headers = _member(make_person, sign_in, name='Hannah')
    assert client.post(f'/events/{slug}/rsvp', headers=guest_headers,
                       json=dict(name='Hannah', party_size=1)).status_code == 201
    rows = client.get(f'/organiser/events/{slug}/rsvps',
                      headers={'X-Organiser-Token': out['token']}).get_json()['going']
    assert rows and all(set(r) <= {'id', 'name', 'party_size', 'attended', 'email'} for r in rows)
