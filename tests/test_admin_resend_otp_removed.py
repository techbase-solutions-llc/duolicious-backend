"""The admin's Resend OTP is gone (TEC-1845 audit, serious 3).

It minted a fresh pending session, emailed its code and threw the bearer
away, so the member's app could never redeem the code. Members request their
own code; there is no admin route to send one."""
from __future__ import annotations

import hashlib
import secrets

from database import api_tx


def test_there_is_no_admin_route_that_sends_a_sign_in_code(client, make_person):
    admin = make_person(name='OtpAdmin')
    member = make_person(name='OtpMember')
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
    r = client.post(f"/admin/users/{member['uuid']}/resend-otp", json={'reason': 'stuck'},
                    headers={'Authorization': f'Bearer {tok}'})
    assert r.status_code == 404
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE person_id = %(i)s',
                          dict(i=member['id'])).fetchone() is None
