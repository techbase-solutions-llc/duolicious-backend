"""Users (TEC-1897; frame W.5): a Last online column, a "Has likes waiting"
filter and push on or off in the drawer."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def _like(a, b) -> None:
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=a['id'], b=b['id']))


def _users(client, headers, q: str, filters: str = '') -> list[dict]:
    r = client.get(f'/admin/users?q={q}&filters={filters}', headers=headers)
    assert r.status_code == 200
    return r.get_json()['rows']


def test_rows_carry_last_online_and_likes_waiting(client, admin_bearer, make_person):
    a, b = make_person(name='UsrLikerQ'), make_person(name='UsrLikedQ')
    _like(a, b)
    row = _users(client, admin_bearer, 'UsrLikedQ')[0]
    assert row['likes_waiting'] == 1
    assert row['last_online_at'].endswith('+00:00')
    assert _users(client, admin_bearer, 'UsrLikerQ')[0]['likes_waiting'] == 0


def test_the_filter_keeps_only_members_with_likes_waiting(client, admin_bearer, make_person):
    tag = uuid4().hex[:8]
    a, b = make_person(name=f'Fa{tag}'), make_person(name=f'Fb{tag}')
    _like(a, b)
    names = {r['name'] for r in _users(client, admin_bearer, tag, 'has_likes_waiting')}
    assert names == {f'Fb{tag}'}
    r = client.get(f'/admin/users?q={tag}&filters=has_likes_waiting', headers=admin_bearer)
    assert r.get_json()['total'] == 1


def test_the_drawer_says_whether_push_is_on(client, admin_bearer, make_person):
    p = make_person(name='UsrPush')
    body = client.get(f"/admin/users/{p['uuid']}", headers=admin_bearer).get_json()['profile']
    assert body['push_devices'] == 0 and body['push_failing'] is False
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, consecutive_failures)
                      VALUES (%(i)s, %(e)s, 'k', 'a', 2)""", dict(i=p['id'], e=f'https://push.test/{uuid4()}'))
    body = client.get(f"/admin/users/{p['uuid']}", headers=admin_bearer).get_json()['profile']
    assert body['push_devices'] == 1 and body['push_failing'] is True
