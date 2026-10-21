"""The Audit log route (TEC-1845 admin audit, Medium).

- days=0 is all time, as on the ledger. It matched nothing before.
- target matches any part of the address, in any case; actor matches the
  whole address in any case; action is exact.
- The response lists the distinct actors and actions, all time, for the
  design's actor dropdown and action pills.
- With no days the route still reads the last 30, as the live admin expects."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx


@pytest.fixture
def old_row():
    tag = uuid4().hex[:10]
    actor = f'auditor-{tag}@example.com'
    target = f'Target-{tag}@Example.com'
    action = f'audit_test_{tag}'
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO admin_audit_log (actor_email, actor_uuid, action, target_email, created_at)
               VALUES (%(a)s, gen_random_uuid(), %(x)s, %(t)s, NOW() - INTERVAL '400 days')""",
            dict(a=actor, x=action, t=target))
    yield dict(tag=tag, actor=actor, target=target, action=action)
    with api_tx() as tx:
        tx.execute('DELETE FROM admin_audit_log WHERE action = %(x)s', dict(x=action))


def _get(client, headers, **params):
    r = client.get('/admin/audit-log', query_string=params, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_days_zero_is_all_time(client, admin_headers, old_row):
    assert _get(client, admin_headers, action=old_row['action'], days=0)['total'] == 1
    assert _get(client, admin_headers, action=old_row['action'], days=30)['total'] == 0


def test_no_days_is_still_the_last_30(client, admin_headers, old_row):
    assert _get(client, admin_headers, action=old_row['action'])['total'] == 0


def test_target_matches_part_of_the_address_in_any_case(client, admin_headers, old_row):
    body = _get(client, admin_headers, target=old_row['tag'].upper(), days=0)
    assert [r['action'] for r in body['rows']] == [old_row['action']]


def test_actor_matches_the_whole_address_in_any_case(client, admin_headers, old_row):
    assert _get(client, admin_headers, actor=old_row['actor'].upper(), days=0)['total'] == 1
    assert _get(client, admin_headers, actor=old_row['tag'], days=0)['total'] == 0


def test_the_actors_and_actions_are_listed(client, admin_headers, old_row):
    body = _get(client, admin_headers, days=30)
    assert old_row['actor'] in body['actors']
    assert old_row['action'] in body['actions']
