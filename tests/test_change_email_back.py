"""Changing your email back to the one you had works (11 Nov 2026).

The session row kept the address it was opened with, and the change-email
request compares the new address against the session's. After A to B the
session still said A, so B back to A answered 400 "New email matches your
current email". A verified change now moves the caller's session to the
new address too.
"""
from __future__ import annotations

import uuid

import service.person as person
from database import api_tx


def _change(client, headers, new_email, sent):
    r = client.post('/account/change-email-request', json={'new_email': new_email}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    code = sent[-1][1]
    r = client.post('/account/change-email-verify', json={'otp': code}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_a_to_b_then_back_to_a(client, make_person, sign_in, monkeypatch):
    sent = []
    monkeypatch.setattr(person, '_send_otp', lambda email, otp, **kw: sent.append((email, otp)))
    a = f'back-a-{uuid.uuid4().hex[:10]}@gmail.com'
    b = f'back-b-{uuid.uuid4().hex[:10]}@gmail.com'
    me = make_person(name='EmailBack', email=a)
    headers = sign_in(me)

    assert _change(client, headers, b, sent) == {'email': b}
    assert _change(client, headers, a, sent) == {'email': a}

    with api_tx() as tx:
        assert tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=me['id'])).fetchone()['email'] == a
        sessions = {r['email'] for r in tx.execute(
            'SELECT email FROM duo_session WHERE person_id = %(i)s', dict(i=me['id'])).fetchall()}
    assert sessions == {a}


def test_the_same_address_as_now_is_still_refused(client, make_person, sign_in, monkeypatch):
    sent = []
    monkeypatch.setattr(person, '_send_otp', lambda email, otp, **kw: sent.append((email, otp)))
    a = f'same-a-{uuid.uuid4().hex[:10]}@gmail.com'
    b = f'same-b-{uuid.uuid4().hex[:10]}@gmail.com'
    headers = sign_in(make_person(name='EmailSame', email=a))
    _change(client, headers, b, sent)
    r = client.post('/account/change-email-request', json={'new_email': b}, headers=headers)
    assert r.status_code == 400
