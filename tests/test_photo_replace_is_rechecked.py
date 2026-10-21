"""A replaced photo is checked again (TEC-1845 admin audit, found alongside
serious 8).

Uploading a photo at a position that already held one updated the row's
uuid, blurhash and hash in place and kept everything else, so the new photo
inherited the old one's moderation_status and nsfw_score. The NSFW cron
picks only unscored pending photos, so the replacement was never checked
and showed wherever the old approval let it. A replacement now starts
exactly as a first upload does: pending, unscored, no face check, no
moderator decision. Until it is checked it behaves as a first upload: it is
not shown in Discover or on the deck, and it does not count towards the
photo gate. The onboarding upload is reset the same way."""
from __future__ import annotations

import base64 as b64lib
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

import duotypes as t
import service.person as sp
from database import api_tx

_RESET = ('moderation_status', 'nsfw_score', 'moderated_at', 'moderation_labels',
          'moderation_confidence', 'face_count', 'face_checked_at', 'face_confirmed_at')


def _image(color: tuple[int, int, int]) -> str:
    img = Image.new('RGB', (64, 64), color=color)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + b64lib.b64encode(buf.getvalue()).decode()


@pytest.fixture(autouse=True)
def _no_object_store(monkeypatch):
    monkeypatch.setattr(sp, 'put_image_in_object_store', lambda *a, **k: None)


def _row(table: str, key: str, value, position: int = 1) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute(
            f"""SELECT uuid, moderation_status::text AS moderation_status, moderated_at,
                       moderation_labels, moderation_confidence
                       {', nsfw_score, face_count, face_checked_at, face_confirmed_at, verified'
                        if table == 'photo' else ''}
                  FROM {table} WHERE {key} = %(v)s AND position = %(pos)s""",
            dict(v=value, pos=position)).fetchone()


def test_a_replaced_profile_photo_starts_unchecked(make_person, add_photo):
    p = make_person(name='Replacer')
    old = add_photo(p['id'], position=1, status='approved', face_count=1, face_confirmed=True)
    with api_tx() as tx:
        tx.execute("""UPDATE photo SET moderated_at = NOW(), moderation_labels = ARRAY['x'],
                             moderation_confidence = 0.9, verified = TRUE WHERE uuid = %(u)s""",
                   dict(u=old))

    req = t.PatchProfileInfo(base64_file=dict(position=1, base64=_image((200, 50, 90)), top=0, left=0))
    sp.patch_profile_info(req, SimpleNamespace(person_id=p['id']))

    row = _row('photo', 'person_id', p['id'])
    assert row['uuid'] != old
    assert row['moderation_status'] == 'pending'
    assert row['nsfw_score'] is None
    assert row['moderated_at'] is None
    assert row['moderation_labels'] == []
    assert row['moderation_confidence'] is None
    assert row['face_count'] is None and row['face_checked_at'] is None
    assert row['face_confirmed_at'] is None
    assert row['verified'] is False

    from service.cron.nsfwphotorunner.sql import Q_50_UNCHECKED_PHOTOS
    every = Q_50_UNCHECKED_PHOTOS.replace('LIMIT\n    50', 'LIMIT\n    1000000')
    with api_tx('read committed') as tx:
        assert row['uuid'] in {r['uuid'] for r in tx.execute(every).fetchall()}, \
            'the classifier must pick the replacement up'


def test_until_checked_it_counts_as_a_first_upload_does(make_person, add_photo):
    """No approved photo left, so the member cannot see others' photos with
    the gate on, and their own photo state reads 'checking', the same as a
    member whose first photo is still waiting."""
    p = make_person(name='ReplacerGate')
    first = make_person(name='FirstUpload')
    add_photo(p['id'], position=1, status='approved', face_count=1)
    add_photo(first['id'], position=1, status='pending', face_count=None)

    req = t.PatchProfileInfo(base64_file=dict(position=1, base64=_image((10, 20, 30)), top=0, left=0))
    sp.patch_profile_info(req, SimpleNamespace(person_id=p['id']))

    with api_tx('read committed') as tx:
        for who in (p, first):
            assert tx.execute('SELECT can_view_photos(%(i)s) AS v', dict(i=who['id'])).fetchone()['v'] is False
            state = tx.execute(sp._Q_OWN_PHOTO_STATE, dict(person_id=who['id'])).fetchone()
            assert state['photo_state'] == 'checking'


def test_a_replaced_onboarding_photo_starts_pending():
    email = f'replace-{uuid4()}@example.com'
    with api_tx() as tx:
        tx.execute('INSERT INTO onboardee (email) VALUES (%(e)s)', dict(e=email))
    try:
        session = SimpleNamespace(email=email)
        sp.patch_onboardee_info(t.PatchOnboardeeInfo(base64_file=dict(
            position=1, base64=_image((1, 2, 3)), top=0, left=0)), session)
        with api_tx() as tx:
            tx.execute("""UPDATE onboardee_photo SET moderation_status = 'approved', moderated_at = NOW(),
                                 moderation_labels = ARRAY['x'], moderation_confidence = 0.9
                           WHERE email = %(e)s""", dict(e=email))
        sp.patch_onboardee_info(t.PatchOnboardeeInfo(base64_file=dict(
            position=1, base64=_image((4, 5, 6)), top=0, left=0)), session)
        row = _row('onboardee_photo', 'email', email)
        assert row['moderation_status'] == 'pending'
        assert row['moderated_at'] is None
        assert row['moderation_labels'] == [] and row['moderation_confidence'] is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))
