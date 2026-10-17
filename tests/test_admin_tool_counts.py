"""Admin > Growth, Couple tools (TEC-1845): counts only, never an answer,
a name or an address."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema')


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


def _us(mode='us') -> int:
    with api_tx() as tx:
        sid = tx.execute(
            """INSERT INTO tool_session (kind, mode, source, claimed_at, completed_at, invite_token,
                                         invite_emails, share_opens, owner_display)
               VALUES ('game', %(m)s, 'tool:game-us', NOW(), NOW(), %(t)s, 2, 3, 'Daniel')
               RETURNING id""", dict(m=mode, t=secrets.token_urlsafe(16))).fetchone()['id']
        tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, display)
                      VALUES (%(s)s, 'guest', %(h)s, 'Rivka')""", dict(s=sid, h=secrets.token_hex(16)))
    return sid


def _row(body, mode):
    return next(r for r in body['modes'] if r['mode'] == mode)


def test_the_counts_are_for_admins_only(client, make_person):
    r = client.get('/admin/growth/tools', headers=_headers(make_person(name='ToolsMember'), False))
    assert r.status_code == 403


def test_the_counts_move_with_the_sessions(client, make_person):
    headers = _headers(make_person(name='ToolsAdmin'), True)
    before = _row(client.get('/admin/growth/tools', headers=headers).get_json(), 'us')
    sid = _us()
    try:
        after = _row(client.get('/admin/growth/tools', headers=headers).get_json(), 'us')
        assert {k: after[k] - before[k] for k in before if k != 'mode'} == dict(
            started=1, completed=1, saved=1, links=1, invite_emails=2, joined=1, guests=1,
            share_opens=3)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))


def test_the_counts_carry_no_answer_or_name(client, make_person):
    headers = _headers(make_person(name='ToolsAdmin2'), True)
    sid = _us()
    try:
        body = client.get('/admin/growth/tools', headers=headers).get_json()
        assert [r['mode'] for r in body['modes']] == ['me', 'us', 'knows_me', 'couple', 'single']
        assert set(body['signups']) == {'tool:game-me', 'tool:game-us', 'tool:knows-me',
                                        'tool:checklist'}
        assert 'Daniel' not in str(body) and 'Rivka' not in str(body)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))
