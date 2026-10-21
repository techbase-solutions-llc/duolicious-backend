"""The drawer's profile carries the member's gender (TEC-1845 admin audit,
Minor 3: the API did not send it)."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx


@pytest.fixture
def admin(make_person):
    p = make_person(name='MinorAdmin')
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
    yield dict(uuid=p['uuid'], headers={'Authorization': f'Bearer {tok}'})
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE actor_uuid = %(u)s::uuid", dict(u=p['uuid']))


def test_the_profile_names_the_members_gender(client, admin, make_person):
    p = make_person(name='Gendered', gender='Woman')
    r = client.get(f"/admin/users/{p['uuid']}", headers=admin['headers'])
    assert r.status_code == 200, r.data
    assert r.get_json()['profile']['gender'] == 'Woman'
