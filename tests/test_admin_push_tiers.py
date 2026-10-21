"""Growth: push subscribers and verification tiers (TEC-1897; frame G.1)."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def _sub(person, *, failures: int = 0, days_ago: int = 0) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, consecutive_failures, created_at)
               VALUES (%(i)s, %(e)s, 'k', 'a', %(f)s, NOW() - make_interval(days => %(d)s))""",
            dict(i=person['id'], e=f'https://push.test/{uuid4()}', f=failures, d=days_ago))


def _push(client, headers, since='2026-10-01') -> dict:
    r = client.get(f'/admin/growth/push?since={since}', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def test_push_counts_members_and_says_which_count_has_staff(client, admin_bearer, make_person):
    a, b, staff = make_person(name='PushA'), make_person(name='PushB'), make_person(name='PushStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = _push(client, admin_bearer)
    _sub(a)
    _sub(a)  # two devices are one member
    _sub(b, failures=3, days_ago=400)  # long before 1 Oct 2026, whenever this runs
    _sub(staff)
    after = _push(client, admin_bearer)
    delta = {k: after[k] - before[k] for k in
             ('members', 'members_with_push', 'with_push_counting_staff', 'members_failing', 'members_new_since')}
    assert delta == dict(members=0, members_with_push=2, with_push_counting_staff=3,
                         members_failing=1, members_new_since=1)
    assert after['since'] == '2026-10-01'


def test_a_bad_since_is_refused(client, admin_bearer):
    assert client.get('/admin/growth/push?since=last-week', headers=admin_bearer).status_code == 400


def test_tiers_count_members_in_order(client, admin_bearer, make_person):
    p, staff = make_person(name='TierGold'), make_person(name='TierStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = client.get('/admin/growth/tiers', headers=admin_bearer).get_json()['tiers']
    assert [t['tier'] for t in before] == ['none', 'bronze', 'silver', 'gold']
    with api_tx() as tx:
        tx.execute("UPDATE person SET ahavah_verification_tier = 'gold' WHERE id = ANY(%(i)s)",
                   dict(i=[p['id'], staff['id']]))
    after = client.get('/admin/growth/tiers', headers=admin_bearer).get_json()['tiers']
    assert {a['tier']: a['members'] - b['members'] for a, b in zip(after, before)} == dict(
        none=-1, bronze=0, silver=0, gold=1)
