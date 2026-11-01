"""A photo whose image is not in the bucket yet is checked again (31 Oct 2026).

The API commits a new photo's row before it uploads the image, and the NSFW
cron polls every second. When the cron reached the row first, the download
failed, the photo was stamped nsfw_score = -1 and, as the cron only picks
rows with no score, it was never checked again: pending, and "Reviewing"
to its owner, for good. A missing image on a photo uploaded in the last
10 minutes now leaves the score empty so the next tick tries again. An
older one is stamped -1 as before, so a photo whose image is really gone
does not hold a place in the queue for ever."""
from __future__ import annotations

import secrets

from database import api_tx
from service.cron.nsfwphotorunner.sql import Q_50_UNCHECKED_PHOTOS, Q_SET_NSFW_SCORE

assert 'LIMIT\n    50' in Q_50_UNCHECKED_PHOTOS
_ALL_UNCHECKED = Q_50_UNCHECKED_PHOTOS.replace('LIMIT\n    50', 'LIMIT\n    1000000')


def _photo(make_person, uploaded_ago: str) -> str:
    p = make_person(name='Missing')
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, blurhash, hash, uploaded_at)
               VALUES (%(u)s, %(p)s, 1, 'testblurhash', gen_random_uuid()::text,
                       NOW() - %(ago)s::interval)""",
            dict(u=uuid, p=p['id'], ago=uploaded_ago))
    return uuid


def _missing(uuid: str) -> None:
    with api_tx() as tx:
        tx.execute(Q_SET_NSFW_SCORE, dict(uuid=uuid, nsfw_score=-1.0, face_count=None))


def _row(uuid: str) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute(
            'SELECT nsfw_score, moderation_status::text AS s FROM photo WHERE uuid = %(u)s',
            dict(u=uuid)).fetchone()


def _picked(uuid: str) -> bool:
    with api_tx('read committed') as tx:
        return uuid in {r['uuid'] for r in tx.execute(_ALL_UNCHECKED).fetchall()}


def test_a_new_photo_with_no_image_yet_is_checked_again(make_person):
    uuid = _photo(make_person, '5 seconds')
    _missing(uuid)
    row = _row(uuid)
    assert row['nsfw_score'] is None
    assert row['s'] == 'pending'
    assert _picked(uuid)


def test_an_old_photo_with_no_image_leaves_the_queue(make_person):
    uuid = _photo(make_person, '1 hour')
    _missing(uuid)
    row = _row(uuid)
    assert row['nsfw_score'] == -1.0
    assert row['s'] == 'pending'
    assert not _picked(uuid)
