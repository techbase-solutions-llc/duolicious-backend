"""/admin/whoami answers a signed-in non-member (an onboardee session) with
is_admin false, so the admin sends them to the unauthorised screen instead
of saying their code was not accepted (TEC-1845 admin audit, Minor 27)."""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

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


def test_whoami_answers_an_onboardee_session_as_not_an_admin(client):
    tok = secrets.token_hex(32)
    email = f'onboardee-{uuid4()}@example.com'
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, NULL, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email))
    try:
        r = client.get('/admin/whoami', headers={'Authorization': f'Bearer {tok}'})
        assert r.status_code == 200, r.data
        assert r.get_json()['is_admin'] is False
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM duo_session WHERE email = %(e)s", dict(e=email))


def test_whoami_still_answers_an_admin(client, admin):
    r = client.get('/admin/whoami', headers=admin['headers'])
    assert r.status_code == 200
    body = r.get_json()
    assert body['is_admin'] is True and body['person_uuid'] == admin['uuid']
