"""The photo cron's face rule and the takedown note (TEC-946).

The verdict SQL is run against real photo rows, because the rule is a CASE
expression and the only way to know which branch a photo takes is to send
one through it.
"""
import hashlib
import io
import secrets
from pathlib import Path

import pytest

from database import api_tx
from service.cron.nsfwphotorunner.sql import Q_SET_NSFW_SCORE


def _photo(person_id, position=1):
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, blurhash, hash)
               VALUES (%(u)s, %(p)s, %(pos)s, 'b', %(h)s)""",
            dict(u=uuid, p=person_id, pos=position, h=secrets.token_hex(16)))
    return uuid


def _score(uuid, nsfw, faces):
    with api_tx() as tx:
        tx.execute(Q_SET_NSFW_SCORE, dict(uuid=uuid, nsfw_score=nsfw, face_count=faces))
        return dict(tx.execute(
            """SELECT moderation_status::text AS s, face_count, face_checked_at
                 FROM photo WHERE uuid = %(u)s""",
            dict(u=uuid)).fetchone())


@pytest.mark.parametrize('position,nsfw,faces,expected', [
    (1, 0.05, 1, 'approved'),        # a face: nothing changes
    (1, 0.05, 0, 'manual_review'),   # primary photo, nobody seen: a person decides
    (2, 0.05, 0, 'approved'),        # a second photo of a landscape is ordinary
    (1, 0.05, None, 'approved'),     # the check did not run: it holds nothing back
    (1, 0.90, 3, 'rejected'),        # the nudity verdict wins, face or not
    (1, 0.50, 1, 'manual_review'),   # borderline nudity is still reviewed
])
def test_the_verdict(make_person, position, nsfw, faces, expected):
    p = make_person(name='FaceRule')
    assert _score(_photo(p['id'], position), nsfw, faces)['s'] == expected


def test_no_face_never_rejects_on_its_own(make_person):
    """A false reject tells a member their own picture is not them. The face
    rule can send a photo to a person; it can never take one down."""
    p = make_person(name='NeverReject')
    assert _score(_photo(p['id']), 0.0, 0)['s'] != 'rejected'


def test_the_count_is_recorded_and_a_failed_check_leaves_it_blank(make_person):
    p = make_person(name='Recorded')
    seen = _score(_photo(p['id']), 0.05, 2)
    assert seen['face_count'] == 2 and seen['face_checked_at'] is not None
    blank = _score(_photo(p['id'], 2), 0.05, None)
    assert blank['face_count'] is None and blank['face_checked_at'] is None


def test_a_download_failure_changes_nothing(make_person):
    p = make_person(name='Missing')
    uuid = _photo(p['id'])
    with api_tx() as tx:
        before = tx.execute(
            "SELECT moderation_status::text AS s FROM photo WHERE uuid = %(u)s",
            dict(u=uuid)).fetchone()['s']
    assert _score(uuid, -1.0, None)['s'] == before


def test_a_detector_that_raises_still_lets_the_run_finish(monkeypatch):
    import service.cron.nsfwphotorunner as runner

    def boom(_):
        raise RuntimeError('model gone')
    monkeypatch.setattr(runner, 'count_faces_in', boom)
    assert runner.count_faces([b'a', b'b']) == [None, None]


FIXTURES = Path(__file__).parent / 'fixtures' / 'facecheck'


def test_the_runner_counts_faces_in_the_shape_the_pipeline_carries():
    """download_450_images hands back BytesIO, not bytes. The detector refuses
    anything but bytes and answers "no faces", so the first draft of this
    would have sent every new main photo to manual review."""
    import service.cron.nsfwphotorunner as runner
    face = io.BytesIO((FIXTURES / 'face-frontal.jpg').read_bytes())
    dog = io.BytesIO((FIXTURES / 'dog.jpg').read_bytes())
    assert runner.count_faces([face, dog]) == [1, 0]


def test_could_not_look_is_unknown_and_never_zero(monkeypatch):
    import antiabuse.facecheck as fc
    assert fc.count_faces(b'not an image') is None
    assert fc.count_faces(io.BytesIO(b'')) is None
    assert fc.count_faces(None) is None
    monkeypatch.setattr(fc, '_get_detector', lambda: None)
    assert fc.count_faces((FIXTURES / 'face-frontal.jpg').read_bytes()) is None


# ---------------------------------------------------------------------------
# The takedown, and the note
# ---------------------------------------------------------------------------

def _admin(make_person):
    p = make_person(name='PhotoAdmin')
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


def _status(uuid):
    with api_tx('read committed') as tx:
        return tx.execute(
            "SELECT moderation_status::text AS s FROM photo WHERE uuid = %(u)s",
            dict(u=uuid)).fetchone()['s']


def test_a_reject_tells_the_member(client, make_person, monkeypatch):
    import service.api.admin.moderation_routes as mr
    sent = []
    monkeypatch.setattr(mr, 'send_photo_removed',
                        lambda email, name=None: sent.append(email) or True)
    p = make_person(name='Told')
    uuid = _photo(p['id'])
    r = client.post(f'/admin/moderation/photos/{uuid}/reject', json={},
                    headers=_admin(make_person))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == dict(ok=True, notified=True)
    assert len(sent) == 1 and _status(uuid) == 'rejected'


def test_notify_false_sends_nothing(client, make_person, monkeypatch):
    import service.api.admin.moderation_routes as mr
    sent = []
    monkeypatch.setattr(mr, 'send_photo_removed',
                        lambda email, name=None: sent.append(email) or True)
    p = make_person(name='Quiet')
    uuid = _photo(p['id'])
    r = client.post(f'/admin/moderation/photos/{uuid}/reject', json=dict(notify=False),
                    headers=_admin(make_person))
    assert r.get_json() == dict(ok=True, notified=False)
    assert sent == [] and _status(uuid) == 'rejected'


def test_a_mailer_that_raises_never_undoes_the_takedown(client, make_person, monkeypatch):
    import service.api.admin.moderation_routes as mr

    def boom(email, name=None):
        raise RuntimeError('smtp down')
    monkeypatch.setattr(mr, 'send_photo_removed', boom)
    p = make_person(name='StillDown')
    uuid = _photo(p['id'])
    r = client.post(f'/admin/moderation/photos/{uuid}/reject', json={},
                    headers=_admin(make_person))
    assert r.status_code == 200 and r.get_json() == dict(ok=True, notified=False)
    assert _status(uuid) == 'rejected'


def test_the_queue_listing_includes_photos_sent_for_review(client, make_person):
    """The Photos tab asked for 'pending' alone, so a photo the cron sent to
    manual_review was shown to nobody."""
    p = make_person(name='Queued')
    uuid = _photo(p['id'])
    _score(uuid, 0.05, 0)
    body = client.get('/admin/moderation/photos?state=queue',
                      headers=_admin(make_person)).get_json()
    rows = body['rows'] if isinstance(body, dict) else body
    mine = [r for r in rows if r.get('photo_uuid', r.get('uuid')) == uuid]
    assert mine, 'a photo sent for review is missing from the queue'
    assert mine[0]['face_count'] == 0 and mine[0]['moderation_status'] == 'manual_review'


def test_the_note_accuses_nobody(monkeypatch):
    import emails.photo_removed as pr
    seen = {}
    monkeypatch.setattr(pr, 'send_member_note', lambda **kw: seen.update(kw) or True)
    assert pr.send_photo_removed('m@ahavah-test.invalid', 'Maxine Doe') is True
    text = ' '.join(seen['paragraphs']).lower()
    for word in ('fake', 'not real', 'violat', 'against our', 'suspicious'):
        assert word not in text
    assert seen['paragraphs'][0] == 'Hi Maxine,'
    assert '—' not in text and seen['cc_admin'] is False
