"""Drawer entitlement actions (TEC-1845 admin audit, Medium): a revoke takes
an optional reason in its body and audits it (the live admin sends none),
and a grant accepts only the names the drawer offers."""
from __future__ import annotations

import pytest

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


def test_a_revoke_audits_the_reason_it_was_given(client, make_person, admin_headers):
    member = make_person(name='Revoked')
    with api_tx() as tx:
        tx.execute("UPDATE person SET entitlements = ARRAY['boost_pack']::TEXT[] WHERE id = %(i)s",
                   dict(i=member['id']))
    try:
        r = client.delete(f"/admin/users/{member['uuid']}/entitlements/boost_pack",
                          json={'reason': 'refunded'}, headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['changed'] is True
        (row,) = _audit_rows(member['uuid'], 'revoke_entitlement')
        assert row['metadata']['reason'] == 'refunded'
    finally:
        _clean_audit(member['uuid'])


def test_a_revoke_without_a_body_still_works(client, make_person, admin_headers):
    """The live admin sends no body."""
    member = make_person(name='Revoked')
    try:
        r = client.delete(f"/admin/users/{member['uuid']}/entitlements/boost_pack",
                          headers=admin_headers)
        assert r.status_code == 200
        assert r.get_json()['changed'] is False
        (row,) = _audit_rows(member['uuid'], 'revoke_entitlement')
        assert row['metadata'].get('reason') is None
    finally:
        _clean_audit(member['uuid'])


@pytest.mark.parametrize('name', ['premium', 'founding_member', 'boost_pack'])
def test_grant_accepts_the_names_the_drawer_offers(client, make_person, admin_headers, name):
    member = make_person(name='Granted')
    try:
        r = client.post(f"/admin/users/{member['uuid']}/entitlements",
                        json={'name': name, 'reason': 'thanks'}, headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        _clean_audit(member['uuid'])


def test_grant_refuses_a_name_nobody_uses(client, make_person, admin_headers):
    member = make_person(name='Granted')
    try:
        r = client.post(f"/admin/users/{member['uuid']}/entitlements",
                        json={'name': 'premum', 'reason': 'typo'}, headers=admin_headers)
        assert r.status_code == 400
        with api_tx() as tx:
            ents = tx.execute('SELECT entitlements FROM person WHERE id = %(i)s',
                              dict(i=member['id'])).fetchone()['entitlements']
        assert 'premum' not in ents
    finally:
        _clean_audit(member['uuid'])
