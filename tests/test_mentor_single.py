"""The single's mentor (TEC-1845, sections 6 and 8): invite, remove, share
one conversation at a time, and the other person always told.

Owner's answer, 21 Oct 2026, item 30: the other member is told a mentor is
reading, in both people's views. The mentor's reading only what was sent
after the share is tested in tests/test_mentor_view.py.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')


@pytest.fixture
def single(make_person, sign_in):
    def _make(name='Rivka Levi', gender='Woman'):
        p = make_person(name=name, gender=gender, email=f'rivka-{uuid4().hex[:8]}@ahavah-test.invalid')
        return p, sign_in(p)
    return _make


def _invite_rows(link_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'mm_mentor_invite' AND mentor_link_id = %(l)s",
            dict(l=link_id)).fetchall()]


def _link(person_id):
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM mentor_link WHERE single_person_id = %(p)s ORDER BY id DESC LIMIT 1',
                         dict(p=person_id)).fetchone()
    return dict(row) if row else None


def test_inviting_sends_one_invitation_and_waits(client, single):
    from service.config import API_BASE_URL, WEB_BASE_URL
    p, h = single()
    address = f'ruth-{uuid4().hex[:8]}@ahavah-test.invalid'
    r = client.post('/mentor/invite', headers=h, json=dict(email=address, relation='parent'))
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json() == dict(state='invited', email=address, relation='parent', shared=[])
    link = _link(p['id'])
    [row] = _invite_rows(link['id'])
    html = row['payload']['html']
    assert row['person_id'] is None and row['lead_id'] is None and row['email'] == address
    assert f'{WEB_BASE_URL}/mentor?invite=' in html and API_BASE_URL + '/mentor' not in html
    assert 'Rivka invited you to be a mentor on Ahavah.' in html and 'as she sees them' in html
    assert client.get('/mentor', headers=h).get_json()['state'] == 'invited'


def test_one_mentor_at_a_time(client, single):
    _p, h = single()
    client.post('/mentor/invite', headers=h, json=dict(email='ruth@ahavah-test.invalid', relation='elder'))
    r = client.post('/mentor/invite', headers=h, json=dict(email='naomi@ahavah-test.invalid', relation='elder'))
    assert r.status_code == 409 and r.get_json()['error'] == 'has_mentor'


def test_cancelling_an_invitation_ends_the_link(client, single):
    p, h = single()
    client.post('/mentor/invite', headers=h, json=dict(email='ruth@ahavah-test.invalid', relation='friend'))
    r = client.delete('/mentor/invite', headers=h)
    assert r.status_code == 200 and r.get_json() == dict(state='none', shared=[])
    assert _link(p['id'])['revoked_at'] is not None
    assert client.post('/mentor/invite', headers=h,
                       json=dict(email='ruth@ahavah-test.invalid', relation='friend')).status_code == 201


def test_an_invitation_to_ones_own_address_is_refused(client, single):
    p, h = single()
    with api_tx('read committed') as tx:
        mine = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    r = client.post('/mentor/invite', headers=h, json=dict(email=mine.upper(), relation='parent'))
    assert r.status_code == 400 and r.get_json()['error'] == 'bad_email'
    assert client.post('/mentor/invite', headers=h, json=dict(email='x@ahavah-test.invalid',
                                                              relation='boss')).status_code == 400


def test_a_refused_address_is_answered_as_invited(client, single, monkeypatch):
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: 'honeypot')
    p, h = single()
    r = client.post('/mentor/invite', headers=h, json=dict(email='ruth@ahavah-test.invalid', relation='parent'))
    assert r.status_code == 201 and r.get_json()['state'] == 'invited' and _link(p['id']) is None


def test_the_confirmed_mentor_and_what_is_shared(client, single_with_mentor):
    single, match, h_single, _h = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    body = client.get('/mentor', headers=h_single).get_json()
    assert body['state'] == 'confirmed' and body['first_name'] == 'Ruth' and body['relation'] == 'parent'
    assert [s['uuid'] for s in body['shared']] == [match['uuid']] and body['shared'][0]['first_name'] == 'Samuel'


def test_sharing_needs_a_confirmed_mentor_and_a_match(client, single, single_with_mentor, make_person):
    s1, match, h_single, _ = single_with_mentor()
    stranger = make_person(name='Stranger')
    r = client.post(f"/conversations/{stranger['uuid']}/share", headers=h_single)
    assert r.status_code == 404 and r.get_json()['error'] == 'not_found'
    assert client.post('/conversations/not-a-uuid/share', headers=h_single).status_code == 404
    lonely, h = single('Naomi')
    with api_tx() as tx:
        tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                   'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                   dict(a=lonely['id'], b=match['id']))
    r = client.post(f"/conversations/{match['uuid']}/share", headers=h)
    assert r.status_code == 409 and r.get_json()['error'] == 'no_mentor'
    client.post('/mentor/invite', headers=h, json=dict(email='ruth@ahavah-test.invalid', relation='parent'))
    assert client.post(f"/conversations/{match['uuid']}/share", headers=h).get_json()['error'] == 'no_mentor'


def test_the_other_person_is_always_told(client, single_with_mentor):
    single, match, h_single, h_match = single_with_mentor()
    assert client.post(f"/conversations/{match['uuid']}/share", headers=h_single).get_json() == {'shared': True}
    theirs = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()
    assert theirs['shared_by_them'] is True and theirs['their_first_name'] == 'Rivka'
    assert [e['kind'] for e in theirs['events']] == ['shared']
    client.delete(f"/conversations/{match['uuid']}/share", headers=h_single)
    assert [e['kind'] for e in client.get(f"/conversations/{single['uuid']}/sharing",
                                          headers=h_match).get_json()['events']] == ['shared', 'stopped']


def test_the_other_members_view_shows_the_notice(client, single_with_mentor):
    """Owner's answer, item 30: the other member is told a mentor is
    reading, in the header and by a line where sharing began."""
    single, match, h_single, h_match = single_with_mentor()
    before = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()
    assert before['notice'] is None and before['events'] == []
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    theirs = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()
    assert theirs['notice'] == 'Rivka’s mentor can read this conversation'
    [line] = theirs['events']
    assert line['by'] == 'them' and line['line'] == (
        'Rivka shared this conversation with their mentor. Messages from now on can be read by them.')
    mine = client.get(f"/conversations/{match['uuid']}/sharing", headers=h_single).get_json()
    assert mine['shared_by_me'] is True and mine['notice'] == 'Shared with your mentor'
    assert mine['events'][0]['line'].startswith('You shared this conversation with your mentor.')
    client.delete(f"/conversations/{match['uuid']}/share", headers=h_single)
    theirs = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()
    assert theirs['notice'] is None and theirs['events'][-1]['line'] == 'Rivka stopped sharing this conversation'


def test_the_notice_stays_while_mentors_are_switched_off(client, single_with_mentor, monkeypatch):
    single, match, h_single, h_match = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    monkeypatch.delenv('AHAVAH_MATCHMAKER_MENTORS_ENABLED')
    r = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match)
    assert r.status_code == 200 and r.get_json()['shared_by_them'] is True


def test_a_member_who_prefers_not_cannot_have_their_conversation_shared(client, single_with_mentor):
    single, match, h_single, h_match = single_with_mentor()
    r = client.patch('/profile-info', headers=h_match, json=dict(no_mentor_shared_matches=True))
    assert r.status_code in (200, 204), r.get_data(as_text=True)
    r = client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    assert r.status_code == 409 and r.get_json()['error'] == 'cannot_share'


def test_removing_a_mentor_ends_every_share_at_once(client, single_with_mentor):
    single, match, h_single, h_match = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    with api_tx() as tx:
        tx.execute("""INSERT INTO mentor_note (mentor_account_id, single_person_id, about_person_id, note)
                      VALUES (%(m)s, %(s)s, %(a)s, 'Ask about his family.')""",
                   dict(m=single['mentor_account_id'], s=single['id'], a=match['id']))
    r = client.delete('/mentor', headers=h_single)
    assert r.status_code == 200 and r.get_json() == dict(state='none', shared=[])
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT count(*) AS n FROM shared_conversation WHERE single_person_id = %(s)s '
                          'AND revoked_at IS NULL', dict(s=single['id'])).fetchone()['n'] == 0
        assert tx.execute('SELECT count(*) AS n FROM mentor_note WHERE single_person_id = %(s)s',
                          dict(s=single['id'])).fetchone()['n'] == 0
    assert client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()['shared_by_them'] is False


_COUNTRY = 'XM'


def test_the_setting_keeps_sharers_out_of_the_deck_and_the_map(client, single_with_mentor, make_person,
                                                               add_photo, sign_in):
    single, match, h_single, _ = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    viewer = make_person(name='Viewer', gender='Man')
    control = make_person(name='Control', gender='Woman')
    add_photo(control['id'])
    with api_tx() as tx:
        for p in (single, control):
            tx.execute("""UPDATE person SET country = %(c)s, show_my_location = TRUE, last_online_time = NOW(),
                                 ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || '{"citySet": true}'::jsonb
                           WHERE id = %(i)s""", dict(c=_COUNTRY, i=p['id']))
        tx.execute('UPDATE person SET activated = TRUE, country = %(c)s WHERE id = %(i)s',
                   dict(c=_COUNTRY, i=viewer['id']))
        tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=control['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute('INSERT INTO search_preference_country (person_id, country) VALUES (%(i)s, %(c)s)',
                   dict(i=viewer['id'], c=_COUNTRY))
    h = sign_in(viewer)

    def seen():
        deck = {c['prospect_uuid'] for c in client.get('/search?n=10&o=0', headers=h).get_json()}
        pins = {m['uuid'] for m in client.get('/map/markers', headers=h).get_json()['markers']}
        return deck, pins

    deck, pins = seen()
    assert {single['uuid'], control['uuid']} <= deck and {single['uuid'], control['uuid']} <= pins
    client.patch('/profile-info', headers=h, json=dict(no_mentor_shared_matches=True))
    deck, pins = seen()
    assert single['uuid'] not in deck and single['uuid'] not in pins
    assert control['uuid'] in deck and control['uuid'] in pins


def test_the_profile_info_carries_the_setting(client, single):
    _p, h = single()
    assert client.get('/profile-info', headers=h).get_json()['no_mentor_shared_matches'] is False
    client.patch('/profile-info', headers=h, json=dict(no_mentor_shared_matches=True))
    assert client.get('/profile-info', headers=h).get_json()['no_mentor_shared_matches'] is True


def test_closed_until_its_switch(client, single, single_with_mentor, monkeypatch):
    s1, match, h_single, h_match = single_with_mentor()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_MENTORS_ENABLED')
    for r in (client.get('/mentor', headers=h_single),
              client.post('/mentor/invite', headers=h_single, json=dict(email='r@ahavah-test.invalid', relation='parent')),
              client.delete('/mentor/invite', headers=h_single), client.delete('/mentor', headers=h_single),
              client.post(f"/conversations/{match['uuid']}/share", headers=h_single),
              client.delete(f"/conversations/{match['uuid']}/share", headers=h_single)):
        assert r.status_code == 404
    assert client.get(f"/conversations/{match['uuid']}/sharing", headers=h_single).status_code == 200
    assert client.patch('/profile-info', headers=h_match, json=dict(no_mentor_shared_matches=True)).status_code in (200, 204)
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert client.get(f"/conversations/{match['uuid']}/sharing", headers=h_single).status_code == 404
    assert client.patch('/profile-info', headers=h_match, json=dict(no_mentor_shared_matches=False)).status_code in (200, 204)
