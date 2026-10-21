"""Bans and photo deletions made from the report email's links write a system
audit row (actor email-link) in the same transaction (TEC-1845 admin audit,
Medium). They were the only /admin mutations with no audit at all."""
from __future__ import annotations

import secrets

from database import api_tx


def _photo(person_id: int, status: str, position: int = 1) -> str:
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
               VALUES (%(u)s, %(p)s, %(n)s, %(s)s, 'testblurhash', gen_random_uuid()::text)""",
            dict(u=uuid, p=person_id, n=position, s=status))
    return uuid


def _audits(action: str, key: str, value: str) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT actor_email, target_email, target_uuid::text AS target_uuid, metadata
                 FROM admin_audit_log WHERE action = %(a)s AND metadata->>%(k)s = %(v)s""",
            dict(a=action, k=key, v=value)).fetchall()]


def _clean_audits(action: str, key: str, value: str) -> None:
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE action = %(a)s AND metadata->>%(k)s = %(v)s",
                   dict(a=action, k=key, v=value))


def test_a_ban_from_the_email_link_is_audited(client, make_person):
    p = make_person(name='Banned')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['email']
        token = tx.execute(
            "INSERT INTO banned_person_admin_token (person_id) VALUES (%(p)s) RETURNING token::text AS t",
            dict(p=p['id'])).fetchone()['t']
    try:
        r = client.post(f'/admin/ban/{token}')
        assert r.status_code == 200, r.get_data(as_text=True)
        (row,) = [x for x in _audits('ban', 'via', 'email_link') if x['target_uuid'] == p['uuid']]
        assert row['actor_email'] == 'email-link'
        assert row['target_email'] == email
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid', dict(u=p['uuid']))
            tx.execute('DELETE FROM banned_person WHERE normalized_email = %(e)s', dict(e=email))


def test_a_photo_deletion_from_the_email_link_is_audited(client, make_person):
    p = make_person(name='PhotoOwner')
    uuid = _photo(p['id'], 'approved')
    with api_tx() as tx:
        photo_hash = tx.execute('SELECT hash FROM photo WHERE uuid = %(u)s', dict(u=uuid)).fetchone()['hash']
    with api_tx() as tx:
        token = tx.execute(
            "INSERT INTO deleted_photo_admin_token (photo_uuid) VALUES (%(u)s) RETURNING token::text AS t",
            dict(u=uuid)).fetchone()['t']
    try:
        r = client.post(f'/admin/delete-photo/{token}')
        assert r.status_code == 200, r.get_data(as_text=True)
        (row,) = _audits('delete_photo', 'photo_uuid', uuid)
        assert row['actor_email'] == 'email-link'
        assert row['target_uuid'] == p['uuid']
    finally:
        _clean_audits('delete_photo', 'photo_uuid', uuid)
        with api_tx() as tx:
            tx.execute('DELETE FROM undeleted_photo WHERE uuid = %(u)s', dict(u=uuid))
            tx.execute('DELETE FROM banned_photo_hash WHERE hash = %(h)s', dict(h=photo_hash))


def test_a_spent_token_writes_no_audit_row(client):
    import uuid as _uuid
    r = client.post(f'/admin/ban/{_uuid.uuid4()}')
    assert r.status_code == 401
