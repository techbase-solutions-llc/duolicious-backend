"""A member's own photo states reach the app (health review, 13 Oct 2026,
finding 93, the data half).

/profile-info returned the member's photos with no moderation status, so
the web marked every one approved and a rejected or held photo showed to
its owner as live. It now carries `photo_moderation_status`, keyed by
position like `photo` and `photo_blurhash`.

/me carries the two fields the photos design brief draws against
(ahavah-web docs/design-briefs/2026-10-13-photos-signup-and-landing.md):
`photo_state`, one of none, checking, held, declined, no_face or ok, and
`photos_locked`, true while the photo gate holds the member. ok means the
member's photos let them see other members' photos, so photo_state never
reads ok while photos_locked is true. Neither field is on the public
/me/<uuid>.
"""
from __future__ import annotations

import pytest

from database import api_tx


@pytest.fixture
def me(make_person, sign_in):
    p = make_person(name='OwnPhotos')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = %(i)s", dict(i=p['id']))
    return dict(id=p['id'], uuid=p['uuid'], headers=sign_in(p))


def _me(client, me):
    r = client.get('/me', headers=me['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


@pytest.mark.parametrize('photos,expected', [
    ([], 'none'),
    ([('pending', None)], 'checking'),
    ([('manual_review', 0)], 'held'),
    ([('rejected', 1)], 'declined'),
    ([('rejected', 1), ('rejected', 0)], 'declined'),
    ([('approved', 0)], 'no_face'),
    ([('approved', 1)], 'ok'),
    ([('approved', None)], 'ok'),          # unchecked passes, as in the gate
    ([('approved', 0), ('approved', 2)], 'ok'),
    ([('rejected', 1), ('approved', 1)], 'ok'),
    # Waiting on a person or a check beats "add a photo that shows you".
    ([('approved', 0), ('pending', None)], 'checking'),
    ([('approved', 0), ('manual_review', 0)], 'held'),
    ([('rejected', 1), ('manual_review', 0)], 'held'),
])
def test_photo_state(client, me, add_photo, monkeypatch, photos, expected):
    monkeypatch.delenv('AHAVAH_PHOTO_GATE_ENABLED', raising=False)
    for position, (status, faces) in enumerate(photos, start=1):
        add_photo(me['id'], position=position, status=status, face_count=faces)
    body = _me(client, me)
    assert body['photo_state'] == expected
    assert body['photos_locked'] is False  # the gate is off


def test_a_photo_a_moderator_confirmed_is_ok(client, me, add_photo):
    add_photo(me['id'], face_count=0, face_confirmed=True)
    assert _me(client, me)['photo_state'] == 'ok'


@pytest.mark.parametrize('photos,locked', [
    ([], True),
    ([('approved', 0)], True),
    ([('manual_review', 1)], True),
    ([('approved', 1)], False),
])
def test_photos_locked_follows_the_gate(client, me, add_photo, monkeypatch, photos, locked):
    monkeypatch.setenv('AHAVAH_PHOTO_GATE_ENABLED', '1')
    for position, (status, faces) in enumerate(photos, start=1):
        add_photo(me['id'], position=position, status=status, face_count=faces)
    body = _me(client, me)
    assert body['photos_locked'] is locked
    assert not (body['photos_locked'] and body['photo_state'] == 'ok')


def test_an_admin_is_never_locked(client, me, monkeypatch):
    monkeypatch.setenv('AHAVAH_PHOTO_GATE_ENABLED', '1')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=me['id']))
    assert _me(client, me)['photos_locked'] is False


def test_the_public_me_carries_neither_field(client, me):
    r = client.get(f"/me/{me['uuid']}")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert 'photo_state' not in body and 'photos_locked' not in body


def test_profile_info_carries_each_photos_moderation_status(client, me, add_photo):
    add_photo(me['id'], position=1, status='rejected')
    add_photo(me['id'], position=2, status='manual_review')
    add_photo(me['id'], position=3, status='pending', face_count=None)
    add_photo(me['id'], position=4)
    r = client.get('/profile-info', headers=me['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['photo_moderation_status'] == {
        '1': 'rejected', '2': 'manual_review', '3': 'pending', '4': 'approved'}


def test_profile_info_with_no_photos_has_no_statuses(client, me):
    r = client.get('/profile-info', headers=me['headers'])
    assert r.get_json()['photo_moderation_status'] is None
