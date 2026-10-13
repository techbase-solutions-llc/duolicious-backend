"""The photo gate (health review, 13 Oct 2026, findings 91 and 99).

A member with no photo of themselves could browse every other member's
photos; only the browser asked for one. With AHAVAH_PHOTO_GATE_ENABLED on,
the API hands such a member no other member's photo ids: the deck, the map,
profiles, the chat header, Views, Liked you and You liked all come back
without photos. Their own profile, matches and conversations keep photos,
and admins are never gated. The rule is can_view_photos() (migration 0062):
an approved photo that shows a face, that a moderator confirmed or that the
detector never looked at.

The switch stays off until the prompt that tells a gated member why ships
(W8). Off, every surface answers as it did before the gate existed; both
states are tested here.

Everyone in the deck tests sits in a user-assigned country code so the
shared database's other people never enter it.
"""
from __future__ import annotations

import pytest

from database import api_tx

_COUNTRY = 'XG'


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_PHOTO_GATE_ENABLED', '1')


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.delenv('AHAVAH_PHOTO_GATE_ENABLED', raising=False)


@pytest.fixture
def world(make_person, add_photo, sign_in):
    """A viewer (a man with no photo yet) and a woman with an approved face
    photo, both on the map and in each other's search country."""
    viewer = make_person(name='GateViewer', gender='Man')
    other = make_person(name='GateOther', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = TRUE, country = %(c)s,
                      show_my_location = TRUE, last_online_time = NOW(),
                      ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                     || '{"citySet": true}'::jsonb
                WHERE id = ANY(%(i)s)""",
            dict(c=_COUNTRY, i=[viewer['id'], other['id']]))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) "
                   "VALUES (%(i)s, %(c)s)", dict(i=viewer['id'], c=_COUNTRY))
    photo = add_photo(other['id'], position=1, face_count=1)
    return dict(viewer=viewer, other=other, photo=photo, headers=sign_in(viewer))


# ---------------------------------------------------------------------------
# What each surface hands the viewer about the other member's photos
# ---------------------------------------------------------------------------

def _deck(client, w):
    r = client.get('/search?n=10&o=0', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [card] = [c for c in r.get_json() if c['prospect_uuid'] == w['other']['uuid']]
    return card['photo_uuids'], card['profile_photo_uuid']


def _map(client, w):
    r = client.get('/map/markers', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [m] = [m for m in r.get_json()['markers'] if m['uuid'] == w['other']['uuid']]
    return m['photo_uuid']


def _profile(client, w, uuid=None):
    r = client.get(f"/prospect-profile/{uuid or w['other']['uuid']}", headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    return j['photo_uuids'], j['photo_blurhashes'], j['photo_extra_exts'], j['photo_verifications']


def _chat_header(client, w):
    r = client.get(f"/conversation-prospect/{w['other']['uuid']}", headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    return j['photo_uuid'], j['photo_blurhash']


def _views(client, w):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
               VALUES (%(s)s, %(o)s, NOW(), FALSE) ON CONFLICT DO NOTHING""",
            dict(s=w['other']['id'], o=w['viewer']['id']))
    r = client.get('/visitors', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [row] = [v for v in r.get_json()['visited_you'] if v['person_uuid'] == w['other']['uuid']]
    return row['photo_uuid'], row['photo_blurhash']


def _liked_you(client, w):
    with api_tx() as tx:
        tx.execute("DELETE FROM liked WHERE liker_id = %(a)s AND liked_id = %(b)s",
                   dict(a=w['viewer']['id'], b=w['other']['id']))
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s) "
                   "ON CONFLICT DO NOTHING", dict(a=w['other']['id'], b=w['viewer']['id']))
        # Liked you lists every liker only for Premium (all members hold it).
        tx.execute("UPDATE person SET entitlements = ARRAY['premium'] WHERE id = %(i)s",
                   dict(i=w['viewer']['id']))
    r = client.get('/likes/incoming', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [like] = [x for x in r.get_json()['likes'] if x['with_profile']['id'] == w['other']['uuid']]
    return like['with_profile']['photo_uuids']


def _you_liked(client, w):
    with api_tx() as tx:
        tx.execute("DELETE FROM liked WHERE liker_id = %(a)s AND liked_id = %(b)s",
                   dict(a=w['other']['id'], b=w['viewer']['id']))
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s) "
                   "ON CONFLICT DO NOTHING", dict(a=w['viewer']['id'], b=w['other']['id']))
    r = client.get('/likes/outgoing', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [like] = [x for x in r.get_json()['likes'] if x['with_profile']['id'] == w['other']['uuid']]
    return like['with_profile']['photo_uuids']


def _limited_profile(client, w):
    with api_tx() as tx:
        tx.execute("UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s",
                   dict(i=w['other']['id']))
    r = client.get(f"/prospect-profile/{w['other']['uuid']}", headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['limited'] is True
    return j['photo_uuids']


# ---------------------------------------------------------------------------
# Gate on: a member with no photo of themselves sees no one's photos
# ---------------------------------------------------------------------------

def test_gate_on_the_deck_has_no_photos(client, world, gate_on):
    assert _deck(client, world) == ([], None)


def test_gate_on_the_map_has_no_photos(client, world, gate_on):
    assert _map(client, world) is None


def test_gate_on_a_profile_has_no_photos(client, world, gate_on):
    assert _profile(client, world) == ([], [], [], [])


def test_gate_on_a_hidden_members_short_profile_has_no_photo(client, world, gate_on):
    assert _limited_profile(client, world) == []


def test_gate_on_the_chat_header_has_no_photo(client, world, gate_on):
    assert _chat_header(client, world) == (None, None)


def test_gate_on_views_has_no_photo(client, world, gate_on):
    assert _views(client, world) == (None, None)


def test_gate_on_liked_you_has_no_photos(client, world, gate_on):
    assert _liked_you(client, world) == []


def test_gate_on_you_liked_has_no_photos(client, world, gate_on):
    assert _you_liked(client, world) == []


# ---------------------------------------------------------------------------
# Gate off: every surface as it was
# ---------------------------------------------------------------------------

def test_gate_off_every_surface_shows_photos(client, world, gate_off):
    p = world['photo']
    assert _deck(client, world) == ([p], p)
    assert _map(client, world) == p
    assert _profile(client, world)[0] == [p]
    assert _chat_header(client, world)[0] == p
    assert _views(client, world)[0] == p
    assert _liked_you(client, world) == [p]
    assert _you_liked(client, world) == [p]
    assert _limited_profile(client, world) == [p]


@pytest.mark.parametrize('value', ['', '0', 'false', 'off', 'no'])
def test_anything_but_a_yes_leaves_the_gate_off(client, world, monkeypatch, value):
    monkeypatch.setenv('AHAVAH_PHOTO_GATE_ENABLED', value)
    assert _profile(client, world)[0] == [world['photo']]


# ---------------------------------------------------------------------------
# Who passes, and who is exempt, with the gate on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('faces,confirmed', [(1, False), (None, False), (0, True)])
def test_a_viewer_with_a_photo_that_shows_them_sees_photos(
        client, world, add_photo, gate_on, faces, confirmed):
    add_photo(world['viewer']['id'], position=3, face_count=faces, face_confirmed=confirmed)
    assert _profile(client, world)[0] == [world['photo']]
    assert _deck(client, world) == ([world['photo']], world['photo'])


@pytest.mark.parametrize('status,faces', [
    ('approved', 0),          # approved, but no face seen and nobody confirmed one
    ('pending', None),        # still being checked
    ('manual_review', 1),     # held for a person
    ('rejected', 1),          # declined
])
def test_a_viewer_without_one_is_gated(client, world, add_photo, gate_on, status, faces):
    add_photo(world['viewer']['id'], position=1, status=status, face_count=faces)
    assert _profile(client, world)[0] == []


def test_a_match_keeps_its_photos(client, world, gate_on):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id)
               VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))""",
            dict(a=world['viewer']['id'], b=world['other']['id']))
    assert _profile(client, world)[0] == [world['photo']]
    assert _chat_header(client, world)[0] == world['photo']


@pytest.mark.parametrize('direction', ['viewer_wrote', 'other_wrote'])
def test_a_conversation_keeps_its_photos(client, world, gate_on, direction):
    a, b = world['viewer']['id'], world['other']['id']
    if direction == 'other_wrote':
        a, b = b, a
    with api_tx() as tx:
        tx.execute("INSERT INTO messaged (subject_person_id, object_person_id) "
                   "VALUES (%(a)s, %(b)s)", dict(a=a, b=b))
    assert _profile(client, world)[0] == [world['photo']]
    assert _views(client, world)[0] == world['photo']


def test_a_member_always_sees_their_own_photos(client, world, add_photo, gate_on):
    mine = add_photo(world['viewer']['id'], position=1, face_count=0)
    assert _profile(client, world, uuid=world['viewer']['uuid'])[0] == [mine]


def test_an_admin_is_never_gated(client, world, gate_on):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=world['viewer']['id']))
    assert _profile(client, world)[0] == [world['photo']]


def test_an_anonymous_visitor_to_a_public_profile_is_unchanged(client, world, gate_on):
    with api_tx() as tx:
        tx.execute("UPDATE person SET public_profile = TRUE WHERE id = %(i)s",
                   dict(i=world['other']['id']))
    r = client.get(f"/prospect-profile/{world['other']['uuid']}")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['photo_uuids'] == [world['photo']]


# ---------------------------------------------------------------------------
# The admin's measure of the gate (finding 99)
# ---------------------------------------------------------------------------

def _admin_headers(make_person, sign_in):
    a = make_person(name='GateAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=a['id']))
    return sign_in(a)


def _gate_kpis(client, headers):
    r = client.get('/admin/moderation/photos?state=queue', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['photo_gate']


@pytest.mark.parametrize('switch', ['gate_on', 'gate_off'])
def test_the_admin_sees_how_many_members_the_gate_holds(
        client, world, make_person, add_photo, sign_in, request, switch):
    request.getfixturevalue(switch)
    headers = _admin_headers(make_person, sign_in)
    before = _gate_kpis(client, headers)
    assert before['enabled'] is (switch == 'gate_on')

    # One more gated member, seen this week and in a conversation.
    gated = make_person(name='GatedCounted')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE, last_online_time = NOW() "
                   "WHERE id = %(i)s", dict(i=gated['id']))
        tx.execute("INSERT INTO messaged (subject_person_id, object_person_id) "
                   "VALUES (%(a)s, %(b)s)", dict(a=gated['id'], b=world['other']['id']))
    # And one who passes, who must not be counted.
    passing = make_person(name='PassingNotCounted')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = %(i)s", dict(i=passing['id']))
    add_photo(passing['id'], face_count=1)

    after = _gate_kpis(client, headers)
    assert after['gated_members'] - before['gated_members'] == 1
    assert after['gated_seen_30_days'] - before['gated_seen_30_days'] == 1
    assert (after['gated_with_match_or_conversation']
            - before['gated_with_match_or_conversation']) == 1
