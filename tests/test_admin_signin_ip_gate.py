"""An admin can sign in from a listed address (2 Oct 2026).

The admin dashboard reaches the API through Vercel's rewrite, so an admin
sign-in arrives from a Vercel egress address. Some are on the FireHOL list,
and the owner was refused at random with "This network is blocked". The
gate now lets an admin's address through; everyone else is still refused.
"""
import hashlib

from database import api_tx
import service.person as person


class _Listed:
    """Every address is on the list."""
    def matches(self, _ip):
        return True


def _email(make_person, name, admin):
    p = make_person(name=name)
    email = f"{name.lower()}-{p['id']}@gatetest.ahavah.app"
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      roles = CASE WHEN %(a)s THEN ARRAY['admin']::text[] ELSE roles END
                WHERE id = %(i)s""", dict(i=p['id'], e=email, a=admin))
    return email


def test_a_member_on_a_listed_address_is_still_refused(client, make_person, monkeypatch):
    monkeypatch.setattr(person, 'firehol', _Listed())
    monkeypatch.setattr(person, '_send_otp', lambda email, otp: None)
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', True)
    email = _email(make_person, 'Listed', admin=False)
    r = client.post('/request-otp', json=dict(email=email))
    assert r.status_code == 460


def test_an_unknown_email_on_a_listed_address_is_refused(client, monkeypatch):
    monkeypatch.setattr(person, 'firehol', _Listed())
    monkeypatch.setattr(person, '_send_otp', lambda email, otp: None)
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', True)
    r = client.post('/request-otp', json=dict(email='nobody-here@gatetest.ahavah.app'))
    assert r.status_code == 460


def _session(email, otp='123456'):
    """A pending sign-in for , made directly so the test does not
    depend on what else the shared test database has banned."""
    import secrets
    token = secrets.token_hex(64)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, otp)
               VALUES (%(h)s, %(e)s, (SELECT id FROM person WHERE email = %(e)s), %(o)s)""",
            dict(h=hashlib.sha512(token.encode()).hexdigest(), e=email, o=otp))
    return {'Authorization': f'Bearer {token}'}


def test_an_admin_on_a_listed_address_may_ask_for_a_code(client, make_person, monkeypatch):
    monkeypatch.setattr(person, 'firehol', _Listed())
    monkeypatch.setattr(person, '_send_otp', lambda email, otp: None)
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', True)
    email = _email(make_person, 'Operator', admin=True)
    r = client.post('/request-otp', json=dict(email=email))
    assert r.status_code == 200, r.get_data(as_text=True)


def test_an_admin_on_a_listed_address_can_use_the_code(client, make_person, monkeypatch):
    monkeypatch.setattr(person, 'firehol', _Listed())
    email = _email(make_person, 'Entering', admin=True)
    r = client.post('/check-otp', json=dict(email=email, otp='123456'), headers=_session(email))
    assert r.status_code == 200, r.get_data(as_text=True)


def test_a_member_on_a_listed_address_cannot_use_a_code(client, make_person, monkeypatch):
    monkeypatch.setattr(person, 'firehol', _Listed())
    email = _email(make_person, 'Refused', admin=False)
    r = client.post('/check-otp', json=dict(email=email, otp='123456'), headers=_session(email))
    assert r.status_code == 460


def test_the_exemption_never_lets_a_wrong_code_through(client, make_person, monkeypatch):
    """Being let past the address check is not being let in."""
    monkeypatch.setattr(person, 'firehol', _Listed())
    email = _email(make_person, 'Guarded', admin=True)
    r = client.post('/check-otp', json=dict(email=email, otp='000000'), headers=_session(email))
    assert r.status_code not in (200, 460)
