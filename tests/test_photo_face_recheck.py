"""A moderator's face confirmation is kept on the photo, and the face rule
runs again when a member's main photo changes (health review, 13 Oct 2026,
findings 97 and 98).

Finding 97: approving a photo in which the detector saw no face set only
the status, so nothing on the photo said a person had looked and accepted
it. `photo.face_confirmed_at` now records that, and a confirmed photo is
never held again.

Finding 98: the face rule ran once, when a photo was first scored, and only
for position 1. Reordering or deleting photos could make a photo with no
face the main one without anyone looking. The rule now runs again after a
reorder, a delete and each scoring pass, against the member's main photo
(the lowest position).

The owner's rule is kept: a photo with no face among photos where the face
shows is left alone. Only a member with no face photo at all has their main
photo held for a person, and it goes to manual_review, never to rejected.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx
from service.photo_rules import (
    Q_RECHECK_MAIN_PHOTO_FACE,
    Q_RECHECK_MAIN_PHOTO_FACE_OF_PHOTOS,
)


def _status(uuid):
    with api_tx('read committed') as tx:
        return dict(tx.execute(
            """SELECT moderation_status::text AS s, face_confirmed_at
                 FROM photo WHERE uuid = %(u)s""",
            dict(u=uuid)).fetchone())


@pytest.fixture
def member(make_person, sign_in):
    p = make_person(name='FaceRecheck')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = %(i)s", dict(i=p['id']))
    return dict(id=p['id'], headers=sign_in(p))


def _admin(make_person):
    p = make_person(name='FaceAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=p['id']))
    return {'Authorization': f'Bearer {tok}'}


# ---------------------------------------------------------------------------
# Finding 97: the moderator's confirmation
# ---------------------------------------------------------------------------

def test_approving_a_photo_with_no_face_records_the_confirmation(client, make_person, add_photo):
    p = make_person(name='Confirmed')
    uuid = add_photo(p['id'], status='manual_review', face_count=0)
    r = client.post(f'/admin/moderation/photos/{uuid}/approve',
                    headers=_admin(make_person))
    assert r.status_code == 200, r.get_data(as_text=True)
    after = _status(uuid)
    assert after['s'] == 'approved' and after['face_confirmed_at'] is not None


@pytest.mark.parametrize('faces', [1, None])
def test_approving_a_photo_the_detector_did_not_flag_confirms_nothing(
        client, make_person, add_photo, faces):
    p = make_person(name='NotFlagged')
    uuid = add_photo(p['id'], status='manual_review', face_count=faces)
    client.post(f'/admin/moderation/photos/{uuid}/approve', headers=_admin(make_person))
    after = _status(uuid)
    assert after['s'] == 'approved' and after['face_confirmed_at'] is None


# ---------------------------------------------------------------------------
# Finding 98: the rule runs again when the main photo changes
# ---------------------------------------------------------------------------

def test_a_reorder_that_puts_a_photo_with_no_face_first_holds_it(client, member, add_photo):
    add_photo(member['id'], position=1, status='manual_review', face_count=0)
    landscape = add_photo(member['id'], position=2, face_count=0)

    r = client.patch('/profile-info', json=dict(photo_assignments={'1': 2, '2': 1}),
                     headers=member['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _status(landscape)['s'] == 'manual_review'


def test_a_delete_that_leaves_a_photo_with_no_face_first_holds_it(client, member, add_photo):
    add_photo(member['id'], position=1, status='rejected', face_count=1)
    landscape = add_photo(member['id'], position=2, face_count=0)

    r = client.delete('/profile-info', json=dict(files=[1]), headers=member['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _status(landscape)['s'] == 'manual_review'


def test_a_photo_with_no_face_among_face_photos_is_left_alone(client, member, add_photo):
    """The owner's rule: only a member with no face photo at all is held."""
    face = add_photo(member['id'], position=1, face_count=1)
    landscape = add_photo(member['id'], position=2, face_count=0)

    r = client.patch('/profile-info', json=dict(photo_assignments={'1': 2, '2': 1}),
                     headers=member['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _status(landscape)['s'] == 'approved'
    assert _status(face)['s'] == 'approved'


def test_a_photo_a_moderator_confirmed_counts_as_a_face_photo(client, member, add_photo):
    add_photo(member['id'], position=1, status='rejected', face_count=1)
    confirmed = add_photo(member['id'], position=2, face_count=0, face_confirmed=True)
    landscape = add_photo(member['id'], position=3, face_count=0)

    client.delete('/profile-info', json=dict(files=[1]), headers=member['headers'])
    assert _status(confirmed)['s'] == 'approved'

    client.patch('/profile-info', json=dict(photo_assignments={'2': 3, '3': 2}),
                 headers=member['headers'])
    assert _status(landscape)['s'] == 'approved'


def test_an_unchecked_main_photo_is_never_held(member, add_photo):
    """No face count means nobody looked; a detector failure holds nothing back."""
    unchecked = add_photo(member['id'], position=1, face_count=None)
    with api_tx() as tx:
        tx.execute(Q_RECHECK_MAIN_PHOTO_FACE, dict(person_ids=[member['id']]))
    assert _status(unchecked)['s'] == 'approved'


def test_scoring_a_photo_that_becomes_the_main_one_runs_the_rule(member, add_photo):
    """Position 1 is empty, so the photo scored at position 2 is the main
    one. The scoring rule looks at position 1 only; the re-check after the
    scoring pass catches it."""
    from service.cron.nsfwphotorunner.sql import Q_SET_NSFW_SCORE
    uuid = add_photo(member['id'], position=2, status='pending', face_count=None)
    with api_tx() as tx:
        tx.execute(Q_SET_NSFW_SCORE, dict(uuid=uuid, nsfw_score=0.05, face_count=0))
        tx.execute(Q_RECHECK_MAIN_PHOTO_FACE_OF_PHOTOS, dict(uuids=[uuid]))
    assert _status(uuid)['s'] == 'manual_review'


def test_the_rule_never_rejects_and_never_releases(member, add_photo):
    held = add_photo(member['id'], position=1, status='manual_review', face_count=0)
    rejected = add_photo(member['id'], position=2, status='rejected', face_count=0)
    with api_tx() as tx:
        tx.execute(Q_RECHECK_MAIN_PHOTO_FACE, dict(person_ids=[member['id']]))
    assert _status(held)['s'] == 'manual_review'
    assert _status(rejected)['s'] == 'rejected'


def test_the_photo_cron_runs_the_rule_after_scoring():
    """The cron cannot be run here without downloading photos, so this pins
    that the scoring pass and the re-check share one transaction."""
    import inspect
    import service.cron.nsfwphotorunner as runner
    src = inspect.getsource(runner.predict_nsfw_photos_once)
    assert src.index('Q_SET_NSFW_SCORE') < src.index('Q_RECHECK_MAIN_PHOTO_FACE_OF_PHOTOS')
