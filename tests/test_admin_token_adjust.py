"""POST /admin/users/<uuid>/tokens (TEC-1845 audit, serious 1).

The route writes ledger reasons 'admin_credit' and 'admin_debit', which
token_ledger_reason_check did not allow, so every manual adjustment returned
500 and rolled its audit row back. Migration 0072 adds both reasons. A debit
larger than the balance is a 409 the admin can show, not an uncaught 500.
The deploy may run the migration more than once, so it is applied twice."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import pytest

from database import api_tx

_MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0072_admin_serious_fixes.sql'


@pytest.fixture(autouse=True)
def _applied_twice():
    for _ in range(2):
        with api_tx() as tx:
            tx.execute(_MIGRATION.read_text(encoding='utf-8'))


def _admin_headers(make_person) -> dict:
    admin = make_person(name='TokenAdmin')
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


def _balance(uuid: str) -> int:
    with api_tx() as tx:
        return int(tx.execute(
            'SELECT COALESCE(SUM(delta), 0) AS b FROM token_ledger WHERE person_id = %(u)s::uuid',
            dict(u=uuid)).fetchone()['b'])


def _audits(uuid: str) -> int:
    with api_tx() as tx:
        return tx.execute(
            """SELECT COUNT(*) AS n FROM admin_audit_log
                WHERE action = 'token_adjust' AND target_uuid = %(u)s::uuid""",
            dict(u=uuid)).fetchone()['n']


def _clean(uuid: str) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid', dict(u=uuid))


def test_a_credit_then_a_debit_both_land_with_their_audit_rows(client, make_person):
    headers = _admin_headers(make_person)
    member = make_person(name='TokenMember')
    try:
        r = client.post(f"/admin/users/{member['uuid']}/tokens",
                        json={'delta': 5, 'reason': 'goodwill'}, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _balance(member['uuid']) == 5

        r = client.post(f"/admin/users/{member['uuid']}/tokens",
                        json={'delta': -2, 'reason': 'correction'}, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _balance(member['uuid']) == 3
        assert _audits(member['uuid']) == 2
    finally:
        _clean(member['uuid'])


def test_a_debit_beyond_the_balance_is_a_409_and_changes_nothing(client, make_person):
    headers = _admin_headers(make_person)
    member = make_person(name='TokenMember')
    try:
        r = client.post(f"/admin/users/{member['uuid']}/tokens",
                        json={'delta': -1, 'reason': 'correction'}, headers=headers)
        assert r.status_code == 409
        assert r.get_json()['error'] == 'insufficient_tokens'
        assert _balance(member['uuid']) == 0
        assert _audits(member['uuid']) == 0
    finally:
        _clean(member['uuid'])


def test_the_constraint_keeps_every_earlier_reason():
    with api_tx() as tx:
        definition = tx.execute(
            """SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint
                WHERE conname = 'token_ledger_reason_check'""").fetchone()['d']
    for reason in ('purchase', 'subscription_stipend', 'reveal_liker', 'super_like',
                   'day_pass', 'boost', 'refund', 'referral', 'rewind',
                   'admin_credit', 'admin_debit'):
        assert f"'{reason}'" in definition, reason
