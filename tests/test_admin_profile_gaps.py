"""Profile gaps, approved photos with no face and the photo gate list
(TEC-1897; frames P.1, P.2 and P.3)."""
from __future__ import annotations

from database import api_tx
from service.admin.queries import profiles


def _gaps(client, headers) -> dict:
    r = client.get('/admin/moderation/profile-gaps', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _gap_of(body, person):
    return next((r['gap'] for r in body['rows'] if r['uuid'] == person['uuid']), None)


def test_each_gap_is_counted_and_listed(client, admin_bearer, make_person, add_photo):
    none_, declined, pending, faceless, fine = (make_person(name=n) for n in
                                                ('GapNone', 'GapDecl', 'GapPend', 'GapFace', 'GapFine'))
    add_photo(declined['id'], status='rejected')
    add_photo(pending['id'], status='pending')
    add_photo(faceless['id'], status='approved', face_count=0)
    add_photo(fine['id'], status='approved', face_count=1)
    body = _gaps(client, admin_bearer)
    assert [_gap_of(body, p) for p in (none_, declined, pending, faceless, fine)] == [
        'no_photo', 'only_declined', 'only_pending', 'no_face', None]
    row = next(r for r in body['rows'] if r['uuid'] == faceless['uuid'])
    assert row['tier'] == 'none' and row['name'] == 'GapFace'


def test_the_strip_moves_with_one_member(client, admin_bearer, make_person):
    before = _gaps(client, admin_bearer)['kpis']
    make_person(name='GapStrip')
    after = _gaps(client, admin_bearer)['kpis']
    assert {k: after[k] - before[k] for k in before} == dict(
        not_verified=1, only_declined=0, no_photo=1, no_face_photo=1)


def test_staff_are_not_profile_gaps(client, admin_bearer, make_person):
    before = _gaps(client, admin_bearer)['kpis']
    staff = make_person(name='GapStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    assert _gaps(client, admin_bearer)['kpis'] == before


def test_approved_with_no_face_lists_unconfirmed_photos_and_marks_staff(client, admin_bearer, make_person, add_photo):
    m, staff = make_person(name='NoFaceMem'), make_person(name='NoFaceStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = client.get('/admin/moderation/photos?state=approved_no_face',
                        headers=admin_bearer).get_json()['approved_no_face']
    listed = add_photo(m['id'], status='approved', face_count=0)
    add_photo(m['id'], position=2, status='approved', face_count=0, face_confirmed=True)
    add_photo(staff['id'], status='approved', face_count=0)
    body = client.get('/admin/moderation/photos?state=approved_no_face', headers=admin_bearer).get_json()
    mine = {r['photo_uuid']: r for r in body['rows'] if r['owner_uuid'] in (m['uuid'], staff['uuid'])}
    assert listed in mine and len(mine) == 2
    assert {r['owner_is_staff'] for r in mine.values()} == {True, False}
    after = body['approved_no_face']
    assert {k: after[k] - before[k] for k in before} == dict(photos=2, people=2, members=1, staff=1)


def test_the_gate_list_carries_activity_and_the_waiting_photo(client, admin_bearer, make_person, add_photo):
    held, other = make_person(name='GateHeld'), make_person(name='GateOther')
    photo = add_photo(held['id'], status='pending')
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=other['id'], b=held['id']))
        tx.execute("""INSERT INTO visited (subject_person_id, object_person_id)
                      VALUES (%(a)s, %(b)s)""", dict(a=other['id'], b=held['id']))
    body = client.get('/admin/moderation/photo-gate', headers=admin_bearer).get_json()
    row = next(r for r in body['members'] if r['uuid'] == held['uuid'])
    assert row['likes_received_30d'] == 1 and row['likes_sent_30d'] == 0
    assert row['profile_views_30d'] == 1 and row['messages_30d'] == 0
    assert row['has_waiting_photo'] is True and row['waiting_photo_uuid'] == photo
    assert row['photo_waiting_since'].endswith('+00:00')
    assert isinstance(body['enabled'], bool)


def test_the_gate_list_reads_no_message_content():
    low = profiles.Q_PHOTO_GATE_MEMBERS.lower()
    for forbidden in ('.message', 'search_body', 'translations', 'audio_uuid'):
        assert forbidden not in low
