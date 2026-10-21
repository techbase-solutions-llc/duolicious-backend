"""Admin deactivate and hard delete keep club.count_members true (TEC-1845
admin audit, Minor 5).

A member's own deactivation and autodeactivate2 take 1 off each of their
clubs, and reactivation and sign-in add it back when they were
deactivated. The admin soft delete and hard delete took nothing off, so
every admin deactivate followed by a reactivate or a sign-in added 1."""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import pytest

from database import api_tx


@pytest.fixture
def club():
    name = f'minor-club-{uuid4().hex[:10]}'
    with api_tx() as tx:
        tx.execute("INSERT INTO club (name, count_members) VALUES (%(n)s, 0)", dict(n=name))
    yield name
    with api_tx() as tx:
        tx.execute("DELETE FROM person_club WHERE club_name = %(n)s", dict(n=name))
        tx.execute("DELETE FROM club WHERE name = %(n)s", dict(n=name))


def _join(person_id: int, club_name: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO person_club (person_id, club_name, activated, coordinates, gender_id)
               SELECT id, %(c)s, activated, coordinates, gender_id FROM person WHERE id = %(p)s""",
            dict(p=person_id, c=club_name))
        tx.execute("UPDATE club SET count_members = count_members + 1 WHERE name = %(c)s",
                   dict(c=club_name))


def _count(club_name: str) -> int:
    with api_tx() as tx:
        return tx.execute("SELECT count_members FROM club WHERE name = %(c)s",
                          dict(c=club_name)).fetchone()['count_members']


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='ClubAdmin')
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
    yield {'Authorization': f'Bearer {tok}'}
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE actor_uuid = %(u)s::uuid", dict(u=p['uuid']))


def test_admin_deactivate_takes_the_member_off_their_clubs(client, admin_headers, make_person, club):
    p = make_person(name='ClubMember')
    _join(p['id'], club)
    assert _count(club) == 1
    r = client.post(f"/admin/users/{p['uuid']}/deactivate", json={'reason': 'test'},
                    headers=admin_headers)
    assert r.status_code == 200, r.data
    assert _count(club) == 0


def test_a_second_deactivate_takes_nothing_more_off(client, admin_headers, make_person, club):
    p = make_person(name='ClubTwice')
    q = make_person(name='ClubOther')
    _join(p['id'], club)
    _join(q['id'], club)
    for _ in range(2):
        r = client.post(f"/admin/users/{p['uuid']}/deactivate", json={'reason': 'test'},
                        headers=admin_headers)
        assert r.status_code == 200, r.data
    assert _count(club) == 1


def test_deactivate_then_reactivate_leaves_the_count_where_it_was(
        client, admin_headers, make_person, club):
    p = make_person(name='ClubRoundTrip')
    _join(p['id'], club)
    client.post(f"/admin/users/{p['uuid']}/deactivate", json={'reason': 'test'},
                headers=admin_headers)
    r = client.post(f"/admin/users/{p['uuid']}/reactivate", json={'reason': 'test'},
                    headers=admin_headers)
    assert r.status_code == 200, r.data
    assert _count(club) == 1


def test_admin_hard_delete_takes_an_active_member_off_their_clubs(
        client, admin_headers, make_person, club):
    p = make_person(name='ClubDeleted')
    _join(p['id'], club)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
    r = client.delete(f"/admin/users/{p['uuid']}",
                      json={'confirm_email': email, 'reason': 'test'}, headers=admin_headers)
    assert r.status_code == 200, r.data
    assert _count(club) == 0


def test_hard_delete_of_a_deactivated_member_takes_nothing_more_off(
        client, admin_headers, make_person, club):
    p = make_person(name='ClubDeactThenDeleted')
    q = make_person(name='ClubStays')
    _join(p['id'], club)
    _join(q['id'], club)
    client.post(f"/admin/users/{p['uuid']}/deactivate", json={'reason': 'test'},
                headers=admin_headers)
    assert _count(club) == 1
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
    r = client.delete(f"/admin/users/{p['uuid']}",
                      json={'confirm_email': email, 'reason': 'test'}, headers=admin_headers)
    assert r.status_code == 200, r.data
    assert _count(club) == 1
