"""Admin query parameters and path uuids (TEC-1845 admin audit, Minor 26).

A malformed uuid on /admin/users/<uuid> and its action routes answers 404,
not a 500 from the ::uuid cast. days, page and expires_within_days are
clamped, so an absurd value in a bookmark answers 200, not a 500 from an
interval or bigint overflow."""
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


_BAD = 'not-a-uuid'


@pytest.mark.parametrize('method,path,body', [
    ('get', f'/admin/users/{_BAD}', None),
    ('patch', f'/admin/users/{_BAD}/roles', {'add': ['mod'], 'reason': 'test'}),
    ('post', f'/admin/users/{_BAD}/deactivate', {'reason': 'test'}),
    ('post', f'/admin/users/{_BAD}/reactivate', {'reason': 'test'}),
    ('post', f'/admin/users/{_BAD}/clear-onboardee', {'reason': 'test'}),
    ('post', f'/admin/users/{_BAD}/tokens', {'delta': 1, 'reason': 'test'}),
    ('post', f'/admin/users/{_BAD}/entitlements', {'name': 'premium', 'reason': 'test'}),
    ('delete', f'/admin/users/{_BAD}/entitlements/premium', None),
    ('delete', f'/admin/users/{_BAD}', {'confirm_email': 'a@b.c', 'reason': 'test'}),
])
def test_a_malformed_uuid_answers_404(client, admin, method, path, body):
    r = getattr(client, method)(path, json=body, headers=admin['headers'])
    assert r.status_code == 404, (path, r.status_code, r.data[:200])


def test_a_malformed_uuid_still_answers_403_to_a_non_admin(client, make_person, sign_in):
    p = make_person(name='NotAdmin')
    r = client.get(f'/admin/users/{_BAD}', headers=sign_in(p))
    assert r.status_code == 403


@pytest.mark.parametrize('path', [
    '/admin/audit-log?days=99999999999',
    '/admin/audit-log?page=1000000000000000000000',
    '/admin/audit-log?days=-5',
    '/admin/economy/ledger?page=1000000000000000000000',
    '/admin/economy/ledger?days=999999999999',
    '/admin/economy/entitlements?expires_within_days=999999999999',
    '/admin/economy/entitlements?expires_within_days=-5',
    '/admin/users?page=1000000000000000000000',
])
def test_absurd_query_parameters_answer_200(client, admin, path):
    r = client.get(path, headers=admin['headers'])
    assert r.status_code == 200, (path, r.status_code, r.data[:200])


def test_negative_days_on_the_audit_log_reads_as_all_time(client, admin):
    r = client.get('/admin/audit-log?days=-5', headers=admin['headers'])
    assert r.get_json()['days'] == 0
