"""Members with no approved photo leave the deck and the map (health review,
13 Oct 2026, finding 95).

Neither the deck nor the map had any photo condition, so a member with no
approved photo showed as a name-seeded gradient that nobody could judge.
On 13 Oct 2026 this was 4 of 58 members in production (all 4 in the deck
pool, 3 of them on the map). They come back as soon as a photo is
approved. On the map a match still sees them; the deck never shows a match.

Everyone here sits in a user-assigned country code so the shared
database's other people never enter the deck.
"""
from __future__ import annotations

import pytest

from database import api_tx

_COUNTRY = 'XP'


@pytest.fixture
def world(make_person, sign_in):
    viewer = make_person(name='NeedsPhotoViewer', gender='Man')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE, country = %(c)s WHERE id = %(i)s",
                   dict(c=_COUNTRY, i=viewer['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) "
                   "VALUES (%(i)s, %(c)s)", dict(i=viewer['id'], c=_COUNTRY))

    def member(name):
        p = make_person(name=name, gender='Woman')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET activated = TRUE, country = %(c)s,
                          show_my_location = TRUE, last_online_time = NOW(),
                          ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                         || '{"citySet": true}'::jsonb
                    WHERE id = %(i)s""",
                dict(c=_COUNTRY, i=p['id']))
        return p

    return dict(viewer=viewer, member=member, headers=sign_in(viewer))


def _deck(client, w):
    r = client.get('/search?n=10&o=0', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    return {c['prospect_uuid'] for c in r.get_json()}


def _map(client, w):
    r = client.get('/map/markers', headers=w['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    return {m['uuid'] for m in r.get_json()['markers']}


@pytest.mark.parametrize('photos', [
    [],
    ['rejected'],
    ['manual_review'],
    ['pending'],
    ['rejected', 'manual_review'],
])
def test_a_member_with_no_approved_photo_is_in_neither(client, world, add_photo, photos):
    shown = world['member']('WithPhoto')
    add_photo(shown['id'])
    hidden = world['member']('NoApproved')
    for position, status in enumerate(photos, start=1):
        add_photo(hidden['id'], position=position, status=status)

    assert _deck(client, world) == {shown['uuid']}
    assert hidden['uuid'] not in _map(client, world)
    assert shown['uuid'] in _map(client, world)


def test_an_approved_photo_without_a_face_is_enough(client, world, add_photo):
    """The face rule is the photo gate's business (finding 91), not this."""
    m = world['member']('Landscape')
    add_photo(m['id'], position=2, face_count=0)
    assert m['uuid'] in _deck(client, world)
    assert m['uuid'] in _map(client, world)


def test_they_come_back_once_a_photo_is_approved(client, world, add_photo):
    m = world['member']('Returns')
    add_photo(m['id'], status='pending', face_count=None)
    assert m['uuid'] not in _deck(client, world)
    with api_tx() as tx:
        tx.execute("UPDATE photo SET moderation_status = 'approved' WHERE person_id = %(i)s",
                   dict(i=m['id']))
    assert m['uuid'] in _deck(client, world)
    assert m['uuid'] in _map(client, world)


def test_a_match_still_sees_them_on_the_map(client, world):
    m = world['member']('MatchedNoPhoto')
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id)
               VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))""",
            dict(a=world['viewer']['id'], b=m['id']))
    assert m['uuid'] in _map(client, world)
