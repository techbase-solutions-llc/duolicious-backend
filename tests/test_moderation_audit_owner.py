"""Moderation routes: the API half of the admin audit's Minor findings
(TEC-1845, 21 Oct).

- Photo approve and reject audit rows name the photo's owner, so the
  Audit tab can find them by member (Minor 16).
- The rude-messages route logs the exception it swallows, since the note
  it answers with tells the owner to see the backend logs (Minor 18)."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx


@pytest.fixture
def admin(make_person):
    p = make_person(name='ModAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    yield dict(uuid=p['uuid'], headers={'Authorization': f'Bearer {tok}'})
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE actor_uuid = %(u)s::uuid", dict(u=p['uuid']))


def _audit_row(actor_uuid: str, action: str) -> dict:
    with api_tx() as tx:
        return dict(tx.execute(
            """SELECT target_email, target_uuid::text AS target_uuid, metadata
                 FROM admin_audit_log
                WHERE actor_uuid = %(a)s::uuid AND action = %(act)s
                ORDER BY id DESC LIMIT 1""",
            dict(a=actor_uuid, act=action)).fetchone())


def _email(person_id: int) -> str:
    with api_tx() as tx:
        return tx.execute("SELECT email FROM person WHERE id = %(i)s",
                          dict(i=person_id)).fetchone()['email']


def test_approve_names_the_photos_owner(client, admin, make_person, add_photo):
    p = make_person(name='PhotoOwner')
    photo = add_photo(p['id'], status='pending')
    r = client.post(f'/admin/moderation/photos/{photo}/approve', headers=admin['headers'])
    assert r.status_code == 200, r.data
    row = _audit_row(admin['uuid'], 'approve_photo')
    assert row['target_uuid'] == p['uuid']
    assert row['target_email'] == _email(p['id'])
    assert row['metadata']['photo_uuid'] == photo


def test_reject_names_the_photos_owner(client, admin, make_person, add_photo):
    p = make_person(name='PhotoOwnerRejected')
    photo = add_photo(p['id'], status='pending')
    r = client.post(f'/admin/moderation/photos/{photo}/reject', json={'notify': False},
                    headers=admin['headers'])
    assert r.status_code == 200, r.data
    row = _audit_row(admin['uuid'], 'reject_photo')
    assert row['target_uuid'] == p['uuid']
    assert row['target_email'] == _email(p['id'])


def test_the_rude_messages_failure_is_logged(client, admin, monkeypatch, capsys):
    import service.api.admin.moderation_routes as mr
    monkeypatch.setattr(mr, 'Q_RUDE_MESSAGES', 'SELECT * FROM no_such_table_minor')
    r = client.get('/admin/moderation/rude-messages', headers=admin['headers'])
    assert r.status_code == 200
    body = r.get_json()
    assert body['rows'] == [] and body['note']
    err = capsys.readouterr().err
    assert 'rude-messages' in err and 'UndefinedTable' in err
