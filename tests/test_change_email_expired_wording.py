"""An expired change-email code says so in a sentence (TEC-2084, Labs F13):
the server answered "Code expired | request a new one", a bar left where a
dash was taken out."""
from __future__ import annotations

import uuid

import service.person as person
from database import api_tx


def test_an_expired_code_reads_as_a_sentence(client, make_person, sign_in, monkeypatch):
    sent = []
    monkeypatch.setattr(person, '_send_otp', lambda email, otp, **kw: sent.append((email, otp)))
    a = f'exp-a-{uuid.uuid4().hex[:10]}@gmail.com'
    b = f'exp-b-{uuid.uuid4().hex[:10]}@gmail.com'
    me = make_person(name='EmailExpired', email=a)
    headers = sign_in(me)
    r = client.post('/account/change-email-request', json={'new_email': b}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx() as tx:
        tx.execute("UPDATE person SET pending_email_otp_expiry = NOW() - INTERVAL '1 minute' "
                   "WHERE id = %(i)s", dict(i=me['id']))
    r = client.post('/account/change-email-verify', json={'otp': sent[-1][1]}, headers=headers)
    assert r.status_code == 400
    assert r.get_data(as_text=True) == 'Code expired. Request a new one.'
