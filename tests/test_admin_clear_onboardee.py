"""Clear onboardee (TEC-1845 admin audit, Medium) says whether there was
anything to clear: it answered ok whether or not an onboardee row existed,
and the admin toasted Cleared. It still deletes every session for the
address, which signs a member out of every device; the admin's dialog says
so, and changing that is the owner's call."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def _clean_audit(uuid: str) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid', dict(u=uuid))


def test_clear_onboardee_with_no_onboardee_says_nothing_was_cleared(
        client, make_person, admin_headers):
    member = make_person(name='Signed in')
    try:
        r = client.post(f"/admin/users/{member['uuid']}/clear-onboardee",
                        json={'reason': 'stuck'}, headers=admin_headers)
        assert r.status_code == 200
        assert r.get_json() == {'ok': True, 'cleared': False}
    finally:
        _clean_audit(member['uuid'])


def test_clear_onboardee_clears_the_row_and_the_sessions(client, make_person, admin_headers):
    member = make_person(name='Half way')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=member['id'])).fetchone()['email']
        tx.execute('INSERT INTO onboardee (email) VALUES (%(e)s)', dict(e=email))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h1)s, %(e)s, %(i)s, TRUE, '123456'),
                      (%(h2)s, %(e)s, NULL, FALSE, '123456')""",
            dict(h1=f'hash-{uuid4()}', h2=f'hash-{uuid4()}', e=email, i=member['id']))
    try:
        r = client.post(f"/admin/users/{member['uuid']}/clear-onboardee",
                        json={'reason': 'stuck'}, headers=admin_headers)
        assert r.status_code == 200
        assert r.get_json() == {'ok': True, 'cleared': True}
        with api_tx() as tx:
            assert tx.execute('SELECT 1 FROM duo_session WHERE email = %(e)s',
                              dict(e=email)).fetchone() is None
            assert tx.execute('SELECT 1 FROM onboardee WHERE email = %(e)s',
                              dict(e=email)).fetchone() is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))
            tx.execute('DELETE FROM duo_session WHERE email = %(e)s', dict(e=email))
        _clean_audit(member['uuid'])
