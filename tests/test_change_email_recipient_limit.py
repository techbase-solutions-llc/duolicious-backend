"""/account/change-email-request is capped per new address (send
safeguards plan, 2 Nov 2026, task 1).

It sends a change-of-email code, which the send guard never halts. Until
now only the default 60 a minute per account bounded it, so a signed-in
caller could aim code after code at one inbox. It now shares the
per-recipient cap of /request-otp: 5 an hour and 20 a day per target
address, from public addresses."""
from __future__ import annotations

import random
import uuid

import service.person as person


def test_the_sixth_request_for_one_new_address_in_an_hour_is_refused(client, make_person, sign_in, monkeypatch):
    sent = []
    monkeypatch.setattr(person, '_send_otp', lambda email, otp, **kw: sent.append((email, kw.get('kind'))))
    headers = sign_in(make_person(name='Changer'))
    client.environ_base['REMOTE_ADDR'] = f'52.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}'
    target = f'change-{uuid.uuid4().hex[:10]}@gmail.com'
    codes = [client.post('/account/change-email-request', json={'new_email': target}, headers=headers).status_code
             for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    assert sent and all(kind == 'change_email_code' for _, kind in sent)
