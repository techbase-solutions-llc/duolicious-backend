"""Moderation shows only the flagged word or phrase (owner, 13 Oct 2026).

A moderator needs to know why a message was flagged, not what the member
wrote. The route returns the listed words the message matched and never
the rest of the message."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx


def _bearer(person_id: int) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=person_id)).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='FlaggedWordsAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
    return _bearer(p['id'])


def test_only_the_flagged_phrase_is_shown(client, make_person, admin_headers):
    import uuid
    email = f'flagged-{uuid.uuid4().hex[:10]}@flaggedtest.ahavah.app'
    sender = make_person(name='FlaggedSender', email=email)
    with api_tx() as tx:
        tx.execute("INSERT INTO rude_message (person_id, created_at, message) VALUES (%(p)s, NOW(), %(m)s)",
                   dict(p=sender['id'], m='Private words about Tuesday then abuse me later zebracorn'))
    r = client.get('/admin/moderation/rude-messages', headers=admin_headers)
    assert r.status_code == 200
    rows = [row for row in r.get_json()['rows'] if row['sender_email'] == email]
    assert rows, r.get_json()
    row = rows[0]
    assert row['snippet'] == 'abuse me'
    body = str(r.get_json())
    assert 'Tuesday' not in body and 'zebracorn' not in body
