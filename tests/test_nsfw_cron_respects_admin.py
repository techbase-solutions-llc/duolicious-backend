"""The NSFW cron never overrides a person's decision (TEC-1845 audit,
serious 8).

The moderation queue shows photos before the classifier has scored them. An
admin's Approve or Take down left nsfw_score NULL, so the cron picked the
photo up and set its status from the score: a taken down photo came back
approved after the member had been told it was removed. The cron now picks
only photos still pending, and its update applies only to a photo still
pending, so a decision made while the classifier runs also stands."""
from __future__ import annotations

import hashlib
import secrets

import pytest

import service.api.admin.moderation_routes as moderation_routes
from database import api_tx
from service.cron.nsfwphotorunner.sql import Q_50_UNCHECKED_PHOTOS, Q_SET_NSFW_SCORE

# Q_50 takes any 50; the shared test database may hold more than 50 pending
# photos, so the test asks the same WHERE without the cap.
assert 'LIMIT\n    50' in Q_50_UNCHECKED_PHOTOS
_ALL_UNCHECKED = Q_50_UNCHECKED_PHOTOS.replace('LIMIT\n    50', 'LIMIT\n    1000000')


@pytest.fixture(autouse=True)
def _no_mail(monkeypatch):
    monkeypatch.setattr(moderation_routes, 'send_photo_removed', lambda *a, **k: True)


@pytest.fixture
def admin_headers(make_person) -> dict:
    admin = make_person(name='PhotoAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def _unscored_photo(make_person) -> str:
    p = make_person(name='Unscored')
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, blurhash, hash)
               VALUES (%(u)s, %(p)s, 1, 'testblurhash', gen_random_uuid()::text)""",
            dict(u=uuid, p=p['id']))
    return uuid


def _picked(uuid: str) -> bool:
    with api_tx('read committed') as tx:
        return uuid in {r['uuid'] for r in tx.execute(_ALL_UNCHECKED).fetchall()}


def _score(uuid: str, score: float) -> None:
    with api_tx() as tx:
        tx.execute(Q_SET_NSFW_SCORE, dict(uuid=uuid, nsfw_score=score, face_count=1))


def _status(uuid: str) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT moderation_status::text AS s FROM photo WHERE uuid = %(u)s',
                          dict(u=uuid)).fetchone()['s']


@pytest.mark.parametrize('action, decided, score', [
    ('reject', 'rejected', 0.05),
    ('approve', 'approved', 0.95),
])
def test_a_decision_on_an_unscored_photo_stands(client, make_person, admin_headers,
                                                action, decided, score):
    uuid = _unscored_photo(make_person)
    assert _picked(uuid), 'a pending photo is scored as before'

    r = client.post(f'/admin/moderation/photos/{uuid}/{action}', headers=admin_headers)
    assert r.status_code == 200

    assert not _picked(uuid), 'the cron must not pick a photo a person decided'
    # A score that lands anyway (the decision came while the classifier ran)
    # leaves the decision alone.
    _score(uuid, score)
    assert _status(uuid) == decided


def test_a_pending_photo_still_gets_its_verdict(make_person):
    uuid = _unscored_photo(make_person)
    _score(uuid, 0.95)
    assert _status(uuid) == 'rejected'
    assert not _picked(uuid)
