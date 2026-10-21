"""Organisers (TEC-1845): the request to host, the magic link and
Ahavah's own organiser."""
import pytest

from database import api_tx
from service.events import EventError

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')


@pytest.fixture(autouse=True)
def _forget_requests():
    """Organisers made through /host-requests have no fixture: delete them
    by their test addresses afterwards."""
    yield
    with api_tx() as tx:
        tx.execute("DELETE FROM organiser WHERE email LIKE 'visitor-%%@ahavah-test.invalid'")


def test_a_request_to_host_makes_a_waiting_organiser_and_lets_them_in(client, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    email, headers = tool_visitor()
    r = client.post('/host-requests', headers=headers, json=dict(
        name='Grace Fellowship', kind='fellowship_leader', city='Dallas', country='United States',
        about='We meet every Sabbath.'))
    assert r.status_code == 201 and r.get_json()['state'] == 'created'
    me = client.get('/organiser/me', headers={'X-Organiser-Token': r.get_json()['token']}).get_json()
    # Task 5 adds the organiser's gatherings under `groups`.
    assert me.pop('groups')['drafts'] == []
    assert me == dict(name='Grace Fellowship', kind='fellowship_leader', approved=False, email=email)


def test_asking_again_says_the_request_is_waiting(client, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    _, headers = tool_visitor()
    body = dict(name='Grace Fellowship', kind='assembly')
    assert client.post('/host-requests', headers=headers, json=body).get_json()['state'] == 'created'
    again = client.post('/host-requests', headers=headers, json=body)
    assert again.status_code == 201 and again.get_json()['state'] == 'pending'
    me = client.get('/organiser/me', headers={'X-Organiser-Token': again.get_json()['token']})
    assert me.status_code == 200 and me.get_json()['approved'] is False


def test_hosting_is_closed_until_its_switch(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_HOSTING_ENABLED', raising=False)
    _, headers = tool_visitor()
    assert client.post('/host-requests', headers=headers, json=dict(name='X', kind='other')).status_code == 404


def test_the_kind_ahavah_cannot_be_asked_for(client, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    _, headers = tool_visitor()
    assert client.post('/host-requests', headers=headers, json=dict(name='X', kind='ahavah')).status_code == 400


def test_a_link_lapses_after_7_days(organiser):
    from service.events.organisers import organiser_for
    o = organiser()
    with api_tx() as tx:
        assert organiser_for(tx, o['token'])['id'] == o['id']
        tx.execute("UPDATE organiser_link SET expires_at = NOW() - interval '1 second' "
                   "WHERE organiser_id = %(o)s", dict(o=o['id']))
    with pytest.raises(EventError) as e:
        with api_tx() as tx:
            organiser_for(tx, o['token'])
    assert (e.value.reason, e.value.status) == ('expired', 401)


def test_a_revoked_organiser_is_locked_out(organiser):
    from service.events.organisers import organiser_for, request_host
    o = organiser()
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET revoked_at = NOW() WHERE id = %(o)s', dict(o=o['id']))
    with pytest.raises(EventError) as e:
        with api_tx() as tx:
            organiser_for(tx, o['token'])
    assert e.value.reason == 'expired'
    with pytest.raises(EventError) as e:
        with api_tx() as tx:
            request_host(tx, email=o['email'], name='X', kind='other', city=None, country=None, about=None)
    assert (e.value.reason, e.value.status) == ('revoked', 403)


def test_an_unknown_or_missing_token_is_expired(client):
    assert client.get('/organiser/me').status_code == 401
    r = client.get('/organiser/me', headers={'X-Organiser-Token': 'x' * 32})
    assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})


def test_asking_for_a_new_link_answers_the_same_whether_or_not_the_address_hosts(client, organiser):
    o = organiser()
    a = client.post('/organisers/link', json=dict(email=o['email']))
    b = client.post('/organisers/link', json=dict(email='nobody-here@ahavah-test.invalid'))
    assert (a.status_code, a.get_json()) == (b.status_code, b.get_json()) == (202, {})


def test_ahavahs_own_organiser_is_approved_at_once(make_person):
    from service.events.organisers import create_organiser, organiser_for, issue_link
    admin = make_person(name='Admin')
    with api_tx() as tx:
        row = create_organiser(tx, name='Ahavah', email='ahavah-own@ahavah-test.invalid',
                               kind='ahavah', admin_person_id=admin['id'])
        token = issue_link(tx, row['id'])
        assert organiser_for(tx, token)['approved'] is True
        tx.execute('DELETE FROM organiser WHERE id = %(i)s', dict(i=row['id']))


def test_everything_is_dark_until_live(client, organiser, tool_visitor, monkeypatch):
    o = organiser()
    _, headers = tool_visitor()
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    assert client.get('/organiser/me', headers=o['headers']).status_code == 404
    assert client.post('/organisers/link', json=dict(email=o['email'])).status_code == 404
    assert client.post('/host-requests', headers=headers, json=dict(name='X', kind='other')).status_code == 404
