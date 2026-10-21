"""Removing the admin role from yourself, or from the last admin, is a 409
(TEC-1845 admin audit, Medium). One mis-tap used to lock every admin out."""
from __future__ import annotations

from database import api_tx


def _audit_rows(uuid: str, action: str) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT metadata FROM admin_audit_log
                WHERE target_uuid = %(u)s::uuid AND action = %(a)s""",
            dict(u=uuid, a=action)).fetchall()]


def _clean_audit(*uuids: str) -> None:
    with api_tx() as tx:
        for u in uuids:
            tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid', dict(u=u))


def _admin_uuid(headers) -> str:
    import hashlib
    tok = headers['Authorization'].split(' ', 1)[1]
    with api_tx() as tx:
        return tx.execute(
            """SELECT p.uuid::text AS u FROM duo_session d JOIN person p ON p.id = d.person_id
                WHERE d.session_token_hash = %(h)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest())).fetchone()['u']


def test_an_admin_cannot_remove_their_own_admin_role(client, admin_headers):
    me = _admin_uuid(admin_headers)
    try:
        r = client.patch(f'/admin/users/{me}/roles',
                         json={'remove': ['admin'], 'reason': 'mistap'}, headers=admin_headers)
        assert r.status_code == 409
        assert r.get_json()['error'] == 'cannot_remove_own_admin'
        with api_tx() as tx:
            roles = tx.execute('SELECT roles FROM person WHERE uuid = %(u)s::uuid',
                               dict(u=me)).fetchone()['roles']
        assert 'admin' in roles
        assert _audit_rows(me, 'patch_roles') == []
    finally:
        _clean_audit(me)


def test_the_last_admin_keeps_the_role(client, make_person, admin_headers, monkeypatch):
    from service.api.admin import users_action_routes as routes
    other = make_person(name='OtherAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=other['id']))
    # The shared test database holds other admins; the rule is what is
    # checked, so the count of the rest is pinned to none.
    monkeypatch.setattr(routes, '_other_admins', lambda tx, person_id: 0)
    try:
        r = client.patch(f"/admin/users/{other['uuid']}/roles",
                         json={'remove': ['admin'], 'reason': 'tidy'}, headers=admin_headers)
        assert r.status_code == 409
        assert r.get_json()['error'] == 'last_admin'
    finally:
        _clean_audit(other['uuid'])


def test_removing_admin_from_another_admin_still_works(client, make_person, admin_headers):
    other = make_person(name='OtherAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=other['id']))
    try:
        r = client.patch(f"/admin/users/{other['uuid']}/roles",
                         json={'remove': ['admin'], 'reason': 'left the team'}, headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['roles'] == []
    finally:
        _clean_audit(other['uuid'])


def test_a_concurrent_removal_cannot_leave_no_admin(client, make_person, admin_headers):
    """Two admins removing each other at once from two workers. The second
    request's transaction began before the first committed; the admin rows
    it locks have changed under it, so it fails to serialize instead of
    removing the last admin as well (write skew under REPEATABLE READ)."""
    import psycopg
    import pytest
    from database import _api_conninfo
    from service.api.admin import users_action_routes as routes
    other = make_person(name='OtherAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=other['id']))
    second = psycopg.connect(_api_conninfo, row_factory=psycopg.rows.dict_row)
    try:
        # The second request has read its snapshot, with `other` an admin.
        second.execute('SELECT roles FROM person WHERE id = %(i)s', dict(i=other['id'])).fetchone()
        r = client.patch(f"/admin/users/{other['uuid']}/roles",
                         json={'remove': ['admin'], 'reason': 'first'}, headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        with pytest.raises(psycopg.errors.SerializationFailure):
            routes._other_admins(second.cursor(), -1)
    finally:
        second.rollback()
        second.close()
        _clean_audit(other['uuid'])


def test_a_serialization_failure_is_a_409(client, make_person, admin_headers, monkeypatch):
    import psycopg
    from service.api.admin import users_action_routes as routes
    other = make_person(name='OtherAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=other['id']))

    def _raise(tx, person_id):
        raise psycopg.errors.SerializationFailure('concurrent update')

    monkeypatch.setattr(routes, '_other_admins', _raise)
    try:
        r = client.patch(f"/admin/users/{other['uuid']}/roles",
                         json={'remove': ['admin'], 'reason': 'race'}, headers=admin_headers)
        assert r.status_code == 409
        assert r.get_json()['error'] == 'conflict'
        with api_tx() as tx:
            roles = tx.execute('SELECT roles FROM person WHERE id = %(i)s',
                               dict(i=other['id'])).fetchone()['roles']
        assert 'admin' in roles
    finally:
        _clean_audit(other['uuid'])
