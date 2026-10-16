"""The Sources table (growth spec, Dashboard; TEC-1845).

One row per source on the taxonomy, with the leads it brought, how many of
them confirmed, the members who signed up from it and how many of those
reached a conversation both people have written in. Members only: staff
and test accounts are left out, as on the rest of the Growth tab. Message
content is never read; this counts rows, as engagement.py does.
"""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('growth_schema')

_MAM_SEQ = [0]


def _uuid_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return str(tx.execute('SELECT uuid FROM person WHERE id = %(i)s',
                              dict(i=person_id)).fetchone()['uuid'])


def _message(sender, recipient) -> None:
    """Two rows, one in each archive, as the chat service writes them
    (copied from tests/test_admin_engagement.py)."""
    _MAM_SEQ[0] += 1
    sender_uuid, recipient_uuid = _uuid_of(sender['id']), _uuid_of(recipient['id'])
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(seq)s AS id",
            dict(seq=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'O', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id, pid=sender['id'], jid=recipient_uuid))
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'I', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id + 1, pid=recipient['id'], jid=sender_uuid))


def _headers(person, admin: bool) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                       dict(i=person['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=person['id']))
    return {'Authorization': f'Bearer {tok}'}


def _set_source(person, source):
    with api_tx() as tx:
        tx.execute('UPDATE person SET lead_source = %(s)s WHERE id = %(i)s',
                   dict(s=source, i=person['id']))


@pytest.fixture
def leads():
    made: list[str] = []

    def add(source: str, confirmed: bool) -> None:
        email = f'src-{uuid4().hex[:10]}@example.org'
        made.append(email)
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO lead (email, normalized_email, source, confirmed_at)
                   VALUES (%(e)s, %(e)s, %(s)s, CASE WHEN %(c)s THEN NOW() END)""",
                dict(e=email, s=source, c=confirmed))

    yield add
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _sources(client, headers) -> dict:
    r = client.get('/admin/growth/sources', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {row['source']: row for row in r.get_json()['sources']}


def test_each_source_counts_its_leads_sign_ups_and_conversations(client, make_person, leads):
    headers = _headers(make_person(name='SrcAdmin'), admin=True)
    source = f'event:src-{uuid4().hex[:8]}'
    a, b = make_person(name='SrcA', gender='Woman'), make_person(name='SrcB', gender='Woman')
    other = make_person(name='SrcOther')
    _set_source(a, source)
    _set_source(b, source)
    leads(source, confirmed=True)
    leads(source, confirmed=False)
    _message(a, other)
    _message(other, a)      # a's conversation has both voices
    _message(b, other)      # b's has one: not a conversation yet
    row = _sources(client, headers)[source]
    assert row == dict(source=source, kind='event', leads=2, confirmed_leads=1,
                       signups=2, conversed=1)


def test_a_source_with_leads_and_no_sign_ups_yet_is_listed(client, make_person, leads):
    headers = _headers(make_person(name='SrcAdmin2'), admin=True)
    source = f'event:src-{uuid4().hex[:8]}'
    leads(source, confirmed=True)
    row = _sources(client, headers)[source]
    assert (row['leads'], row['signups'], row['conversed']) == (1, 0, 0)


def test_staff_are_not_counted(client, make_person):
    headers = _headers(make_person(name='SrcAdmin3'), admin=True)
    source = f'tool:src-{uuid4().hex[:8]}'
    staff = make_person(name='SrcStaff')
    _headers(staff, admin=True)
    _set_source(staff, source)
    assert source not in _sources(client, headers)


def test_members_with_no_source_are_one_unknown_row(client, make_person):
    headers = _headers(make_person(name='SrcAdmin4'), admin=True)
    make_person(name='SrcUnknown')
    row = _sources(client, headers)['unknown']
    assert row['kind'] == 'unknown' and row['signups'] >= 1


def test_the_table_is_for_admins_only(client, make_person):
    member = _headers(make_person(name='SrcMember'), admin=False)
    assert client.get('/admin/growth/sources', headers=member).status_code == 403
