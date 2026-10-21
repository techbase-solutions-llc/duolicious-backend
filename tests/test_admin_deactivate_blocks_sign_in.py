"""An admin deactivation holds until an admin reactivates (TEC-1845 audit,
serious 2).

It used to set activated = FALSE only, and the next successful sign-in set it
back to TRUE, so a member deactivated for abuse was back the next time they
asked for a code. person.admin_deactivated_at now blocks sign-in. The member
still gets a code (so /request-otp answers exactly as for any account and
reveals nothing), and only once they enter the right code are they told the
account is deactivated: 403 'Account deactivated', with the session left
signed out. A claim link is refused the same way. A member's own
deactivation, or the inactivity cron's, still ends at the next sign-in."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx

CLIENT = '45.33.20.10'


def _admin_headers(make_person) -> dict:
    admin = make_person(name='LifecycleAdmin')
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
    return {'Authorization': f'Bearer {tok}'}


def _email(person) -> str:
    with api_tx() as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=person['id'])).fetchone()['email']


def _state(person) -> dict:
    with api_tx() as tx:
        return tx.execute(
            'SELECT activated, admin_deactivated_at FROM person WHERE id = %(i)s',
            dict(i=person['id'])).fetchone()


def _signed_in(token: str) -> bool:
    with api_tx() as tx:
        row = tx.execute(
            'SELECT signed_in FROM duo_session WHERE session_token_hash = %(h)s',
            dict(h=hashlib.sha512(token.encode()).hexdigest())).fetchone()
    return bool(row and row['signed_in'])


def _sign_in(client, signup_env, email):
    """/request-otp then /check-otp with the code an @example.com account is
    always given. Returns the /request-otp token and the /check-otp reply."""
    r = signup_env.request(email, ip=CLIENT)
    assert r.status_code == 200, r.get_data(as_text=True)
    token = r.get_json()['session_token']
    assert signup_env.issued(token), 'a code is issued as for any account'
    ok = client.post('/check-otp', json=dict(email=email, otp='000000'),
                     headers={'Authorization': f'Bearer {token}'},
                     environ_base={'REMOTE_ADDR': CLIENT})
    return token, ok


@pytest.fixture
def audit_cleanup():
    uuids: list[str] = []
    yield uuids
    with api_tx() as tx:
        tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = ANY(%(u)s::uuid[])',
                   dict(u=uuids))


def test_a_deactivated_member_is_told_and_stays_signed_out_until_reactivated(
        client, signup_env, make_person, audit_cleanup):
    headers = _admin_headers(make_person)
    member = make_person(name='Deactivated')
    audit_cleanup.append(member['uuid'])
    email = _email(member)

    r = client.post(f"/admin/users/{member['uuid']}/deactivate",
                    json={'reason': 'abuse'}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _state(member)['admin_deactivated_at'] is not None
    detail = client.get(f"/admin/users/{member['uuid']}", headers=headers).get_json()
    assert detail['profile']['admin_deactivated'] is True, 'the drawer offers Reactivate'

    token, refused = _sign_in(client, signup_env, email)
    assert refused.status_code == 403
    assert refused.get_data(as_text=True) == 'Account deactivated'
    assert not _signed_in(token), 'the session must not be signed in'
    assert _state(member)['activated'] is False

    # A wrong code is still just a wrong code: nothing about the account.
    wrong = client.post('/check-otp', json=dict(email=email, otp='999999'),
                        headers={'Authorization': f'Bearer {token}'},
                        environ_base={'REMOTE_ADDR': CLIENT})
    assert wrong.status_code == 401

    r = client.post(f"/admin/users/{member['uuid']}/reactivate",
                    json={'reason': 'appeal upheld'}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _state(member)['admin_deactivated_at'] is None
    detail = client.get(f"/admin/users/{member['uuid']}", headers=headers).get_json()
    assert detail['profile']['admin_deactivated'] is False

    token, ok = _sign_in(client, signup_env, email)
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert _signed_in(token)
    assert _state(member)['activated'] is True


def test_a_deactivation_that_was_not_an_admin_block_still_ends_at_sign_in(
        client, signup_env, make_person):
    member = make_person(name='SelfDeactivated')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=member['id']))
    token, ok = _sign_in(client, signup_env, _email(member))
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert _state(member)['activated'] is True


def test_a_claim_link_does_not_sign_in_a_deactivated_member(client, make_person):
    from service.unsubscribe import make_token

    member = make_person(name='ClaimDeactivated')
    email = _email(member)
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = FALSE, admin_deactivated_at = NOW() WHERE id = %(i)s',
                   dict(i=member['id']))
    r = client.post('/claim', json={'token': make_token('claim', email)})
    assert r.status_code == 403
    assert r.get_json() == {'error': 'account_deactivated'}
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE person_id = %(i)s',
                          dict(i=member['id'])).fetchone() is None


def test_an_admin_cannot_deactivate_their_own_account(client, make_person):
    # Deactivate holds until an admin reactivates and deletes the caller's
    # sessions, so deactivating yourself would lock you out of the admin.
    admin = make_person(name='SelfLockAdmin')
    email = _email(admin)
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))

    r = client.post(f"/admin/users/{admin['uuid']}/deactivate",
                    json={'reason': 'mis-tap'}, headers={'Authorization': f'Bearer {tok}'})
    assert r.status_code == 409
    assert r.get_json() == {'error': 'cannot_deactivate_self'}
    assert _state(admin)['admin_deactivated_at'] is None
    assert _state(admin)['activated'] is True
    assert _signed_in(tok), 'the admin keeps their session'
