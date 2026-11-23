"""Admin > Users > Reactivate keeps a member who asked to be deleted
(TEC-2170).

The reactivate set the account active but left deletion_requested_at, so a
member with a pending deletion was still hard-deleted by the
pendingdeletion cron once the 7 days ran out. It now clears the request
and marks the member's open exit answer kept, in the same transaction as
the audit entry, as the member's own cancel-deletion does. A reactivate of
a member with no pending deletion is unchanged."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from database import api_tx


@pytest.fixture
def cleanup():
    """Exit answers outlive their person and audit rows are keyed by uuid,
    so make_person's teardown removes neither."""
    uuids: list[str] = []
    with api_tx() as tx:
        before = tx.execute('SELECT COALESCE(MAX(id), 0) AS m FROM exit_answer').fetchone()['m']
    yield uuids
    with api_tx() as tx:
        tx.execute('DELETE FROM exit_answer WHERE id > %(m)s', dict(m=before))
        tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = ANY(%(u)s::uuid[])',
                   dict(u=uuids))


def _person(person) -> dict | None:
    with api_tx() as tx:
        return tx.execute(
            'SELECT activated, deletion_requested_at, admin_deactivated_at '
            'FROM person WHERE id = %(p)s', dict(p=person['id'])).fetchone()


def _answer(note: str) -> dict:
    with api_tx() as tx:
        rows = tx.execute('SELECT * FROM exit_answer WHERE note = %(n)s',
                          dict(n=note)).fetchall()
    assert len(rows) == 1
    return rows[0]


def _audit(person) -> list[dict]:
    with api_tx() as tx:
        return tx.execute(
            "SELECT action, metadata FROM admin_audit_log "
            "WHERE target_uuid = %(u)s::uuid AND action = 'reactivate'",
            dict(u=person['uuid'])).fetchall()


def _reactivate(client, admin_bearer, person):
    r = client.post(f"/admin/users/{person['uuid']}/reactivate",
                    json={'reason': 'asked to stay'}, headers=admin_bearer)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {'ok': True}


def test_a_reactivated_pending_account_survives_the_purge(
        client, sign_in, admin_bearer, make_person, cleanup):
    from service.cron.pendingdeletion import hard_delete_expired_once

    p = make_person(name='ReactivatedLeaver')
    cleanup.append(p['uuid'])
    note = f'reactivated-{uuid4()}'
    r = client.delete('/account', headers=sign_in(p),
                      json=dict(reason='break', note=note))
    assert r.status_code == 200, r.get_data(as_text=True)
    # Past the 7 days, and not signed in since the request: the purge
    # would take this account.
    with api_tx() as tx:
        tx.execute("UPDATE person SET deletion_requested_at = NOW() - INTERVAL '8 days', "
                   "sign_in_time = NOW() - INTERVAL '9 days' WHERE id = %(p)s",
                   dict(p=p['id']))
    assert _answer(note)['person_id'] == p['id']

    _reactivate(client, admin_bearer, p)

    state = _person(p)
    assert state['activated'] is True
    assert state['deletion_requested_at'] is None, 'the deletion request must be cleared'

    kept = _answer(note)
    assert kept['kept_at'] is not None and kept['person_id'] is None, \
        'the exit answer must be marked kept'

    audit = _audit(p)
    assert len(audit) == 1
    assert audit[0]['metadata']['reason'] == 'asked to stay'

    asyncio.run(hard_delete_expired_once())

    assert _person(p) is not None, 'the purge deleted a reactivated member'


def test_a_reactivate_with_no_pending_deletion_is_unchanged(
        client, admin_bearer, make_person, cleanup):
    p = make_person(name='ReactivatedBlocked')
    cleanup.append(p['uuid'])
    r = client.post(f"/admin/users/{p['uuid']}/deactivate",
                    json={'reason': 'test'}, headers=admin_bearer)
    assert r.status_code == 200, r.get_data(as_text=True)

    _reactivate(client, admin_bearer, p)

    state = _person(p)
    assert state['activated'] is True
    assert state['admin_deactivated_at'] is None
    assert state['deletion_requested_at'] is None
    audit = _audit(p)
    assert len(audit) == 1
    assert audit[0]['metadata']['reason'] == 'asked to stay'


def test_a_reactivate_of_an_unknown_member_is_404(client, admin_bearer):
    r = client.post(f'/admin/users/{uuid4()}/reactivate',
                    json={'reason': 'x'}, headers=admin_bearer)
    assert r.status_code == 404
