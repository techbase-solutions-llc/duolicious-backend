"""Start a matchmaking profile from Your Ahavah without a second code
(TEC-1845, release 4 follow-up; design 4.2: "No new code is needed,
because the address was confirmed a moment ago").

POST /your-ahavah/start-profile takes a live address session and hands
back what /request-otp and a right code at /check-otp would have: a signed-in
sign-up session for the address, made by the same code. The address
session ends once used. A member's address is refused (409 member), a
lapsed session too (401 expired), and every other refusal leaves the web
to fall back to the usual code step."""
import hashlib
import random
from uuid import uuid4

import pytest

from database import api_tx
from service import your_ahavah

pytestmark = pytest.mark.usefixtures('events_schema', 'matchmaker_schema', 'release_4_schema', 'events_live',
                                     'matchmaker_live', 'light_on', 'mail_allowed', 'signups_open')

PATH = '/your-ahavah/start-profile'


@pytest.fixture
def light_on(monkeypatch, client):
    monkeypatch.setenv('AHAVAH_LIGHT_SIGN_IN_ENABLED', '1')
    # A private address of its own each test, so the per-network limits
    # start empty (they live in the shared Redis) and no ban on 127.0.0.1
    # from another test applies.
    client.environ_base['REMOTE_ADDR'] = f'10.{random.randint(1, 254)}.{random.randint(1, 254)}.' \
                                         f'{random.randint(1, 254)}'


@pytest.fixture
def signups_open(monkeypatch):
    import service.person as person
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', True)


@pytest.fixture
def codes(monkeypatch):
    """Every Your Ahavah code that would be mailed, and every sign-up code
    (person._send_otp), captured: neither is sent."""
    import service.person as person
    sent = dict(address=[], sign_up=[])
    monkeypatch.setattr(your_ahavah, 'send_code', lambda email, code: sent['address'].append((email, code)))
    monkeypatch.setattr(person, '_send_otp', lambda email, code: sent['sign_up'].append((email, code)))
    return sent


@pytest.fixture
def address():
    made: list[str] = []

    def _make() -> str:
        a = f'start-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(a)
        return a

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM address_session WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM duo_session WHERE email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM onboardee WHERE email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM lead WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM tool_session WHERE owner_normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM person WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM banned_person WHERE normalized_email = ANY(%(e)s)', dict(e=made))


def _sign_in(client, codes, email) -> dict:
    r = client.post('/your-ahavah/code', json=dict(email=email))
    assert r.status_code == 202, r.get_data(as_text=True)
    handle = r.get_json()['request_token']
    code = next(c for e, c in reversed(codes['address']) if e == email)
    r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=code))
    assert r.status_code == 200, r.get_json()
    return {'X-Address-Token': r.get_json()['address_token']}


def _session(token: str):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM duo_session WHERE session_token_hash = %(h)s',
                          dict(h=hashlib.sha512(token.encode()).hexdigest())).fetchone()


def _check_otp_answer(client, email) -> dict:
    """What /check-otp answers a new address after the right code, through
    the real route: the shape the new route must match."""
    import secrets
    tok = secrets.token_hex(64)
    with api_tx() as tx:
        tx.execute("INSERT INTO duo_session (session_token_hash, email, otp) VALUES (%(h)s, %(e)s, '123456')",
                   dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email))
    r = client.post('/check-otp', json=dict(otp='123456'), headers={'Authorization': f'Bearer {tok}'})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# ---------------------------------------------------------------------------
# Dark
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('off', ['AHAVAH_LIGHT_SIGN_IN_ENABLED', 'AHAVAH_MATCHMAKER_LIVE_ENABLED'])
def test_absent_while_a_switch_is_off(client, monkeypatch, codes, address, off):
    headers = _sign_in(client, codes, address())
    monkeypatch.delenv(off)
    r = client.post(PATH, json={}, headers=headers)
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})


# ---------------------------------------------------------------------------
# The sign-up, with no second code
# ---------------------------------------------------------------------------

def test_it_answers_what_the_code_step_would_and_mails_nothing(client, codes, address):
    a = address()
    headers = _sign_in(client, codes, a)
    r = client.post(PATH, json={}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers['Cache-Control'] == 'no-store'
    out = r.get_json()
    token = out.pop('session_token')
    assert isinstance(token, str) and len(token) == 128
    assert out['onboarded'] is False and out['person_id'] is None
    # The same keys /check-otp answers a new address with.
    assert set(out) == set(_check_otp_answer(client, address()))
    # A signed-in sign-up session for the address, as /check-otp leaves it,
    # with its code spent.
    s = _session(token)
    assert (s['email'], s['person_id'], s['signed_in']) == (a, None, True)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT otp_expiry <= NOW() AS spent FROM duo_session WHERE session_token_hash = %(h)s',
                          dict(h=s['session_token_hash'])).fetchone()['spent']
        assert tx.execute('SELECT 1 FROM onboardee WHERE email = %(e)s', dict(e=a)).fetchone() is not None
    # No sign-up code went out.
    assert codes['sign_up'] == []


def test_the_session_opens_the_onboarding_routes(client, codes, address):
    a = address()
    token = client.post(PATH, json={}, headers=_sign_in(client, codes, a)).get_json()['session_token']
    r = client.patch('/onboardee-info', json=dict(name='Ruth'), headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT name FROM onboardee WHERE email = %(e)s', dict(e=a)).fetchone()['name'] == 'Ruth'


def test_the_address_session_ends_once_used(client, codes, address):
    a = address()
    headers = _sign_in(client, codes, a)
    assert client.post(PATH, json={}, headers=headers).status_code == 200
    assert client.get('/your-ahavah', headers=headers).get_json() == {'error': 'expired'}
    again = client.post(PATH, json={}, headers=headers)
    assert (again.status_code, again.get_json()) == (401, {'error': 'expired'})
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT count(*)::int AS n FROM duo_session WHERE email = %(e)s',
                          dict(e=a)).fetchone()['n'] == 1


def test_the_source_and_the_referral_travel_as_on_the_code_step(client, codes, address):
    a = address()
    r = client.post(PATH, json=dict(source='alert:visitor'), headers=_sign_in(client, codes, a))
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                          dict(e=a)).fetchone()['lead_source'] == 'alert:visitor'
    # A source the web did not expect is no source, never a 400.
    b = address()
    r = client.post(PATH, json=dict(source=7), headers=_sign_in(client, codes, b))
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                          dict(e=b)).fetchone()['lead_source'] is None


def test_finishing_the_sign_up_brings_across_what_the_address_holds(client, codes, address, published,
                                                                    confirmed_guest, monkeypatch):
    """The finish-sign-up carry-over runs as after a code: the RSVPs, the
    saved Together results, the confirmed leads and the visitor alert."""
    import json
    import emails.member_welcome
    import emails.waitlist_admin
    import service.person as person
    from service.leads import confirm_lead, record_lead
    from service.leads.sources import ALERT_VISITOR
    monkeypatch.setattr(person.metapixel, 'send_complete_registration', lambda **kw: None)
    monkeypatch.setattr(emails.member_welcome, 'send_member_welcome_async', lambda *a, **kw: None)
    monkeypatch.setattr(emails.waitlist_admin, 'send_new_signup_notice_async', lambda *a, **kw: None)

    a = address()
    place = confirmed_guest(published(), email=a, name='Ruth Sender')
    with api_tx() as tx:
        sid = tx.execute(
            """INSERT INTO tool_session (kind, mode, source, owner_email, owner_normalized_email, owner_display,
                                         claimed_at, completed_at)
               VALUES ('game', 'me', 'tool:game-me', %(e)s, %(e)s, 'Ruth', NOW(), NOW()) RETURNING uuid::text""",
            dict(e=a)).fetchone()['uuid']
        lead = record_lead(tx, email=a, source=ALERT_VISITOR)
        confirm_lead(tx, lead, 'link')
        tx.execute("""INSERT INTO match_alert (lead_id, first_name, criteria, confirmed_at)
                      VALUES (%(l)s, 'Ruth', %(c)s::jsonb, NOW())""",
                   dict(l=lead, c=json.dumps(dict(age_min=25, age_max=35, region='europe'))))

    token = client.post(PATH, json={}, headers=_sign_in(client, codes, a)).get_json()['session_token']
    with api_tx() as tx:
        tx.execute("""UPDATE onboardee SET name = 'Ruth', date_of_birth = '1992-02-02',
                             coordinates = ST_SetSRID(ST_MakePoint(-59.6, 13.1), 4326)::geography,
                             gender_id = (SELECT id FROM gender WHERE name = 'Woman')
                       WHERE email = %(e)s""", dict(e=a))
        tx.execute("""INSERT INTO onboardee_photo (email, position, uuid, blurhash, hash, moderation_status)
                      VALUES (%(e)s, 1, %(u)s, 'blur', %(h)s, 'pending')""",
                   dict(e=a, u=uuid4().hex + uuid4().hex, h=uuid4().hex))
    r = client.post('/finish-onboarding', json={}, headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        pid = tx.execute('SELECT id FROM person WHERE email = %(e)s', dict(e=a)).fetchone()['id']
        assert tx.execute('SELECT person_id FROM event_rsvp WHERE id = %(i)s',
                          dict(i=place['id'])).fetchone()['person_id'] == pid
        assert tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s::uuid',
                          dict(u=sid)).fetchone()['owner_person_id'] == pid
        assert tx.execute('SELECT 1 FROM match_alert WHERE person_id = %(p)s', dict(p=pid)).fetchone()
        assert tx.execute('SELECT count(*)::int AS n FROM lead WHERE normalized_email = %(e)s AND person_id IS NULL',
                          dict(e=a)).fetchone()['n'] == 0


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_a_members_address_is_refused_and_keeps_its_session(client, codes, address, make_person):
    a = address()
    make_person(name='Miriam Member', email=a)
    headers = _sign_in(client, codes, a)
    r = client.post(PATH, json={}, headers=headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'member'})
    assert client.get('/your-ahavah', headers=headers).status_code == 200
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE email = %(e)s', dict(e=a)).fetchone() is None


def test_a_lapsed_or_missing_session_is_refused(client, codes, address):
    a = address()
    headers = _sign_in(client, codes, a)
    with api_tx() as tx:
        tx.execute("UPDATE address_session SET session_expires_at = NOW() - INTERVAL '1 second' "
                   "WHERE normalized_email = %(e)s", dict(e=a))
    for h in (headers, {}, {'X-Address-Token': 'z' * 43}):
        r = client.post(PATH, json={}, headers=h)
        assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE email = %(e)s', dict(e=a)).fetchone() is None


def test_a_member_session_does_not_open_it(client, make_person, sign_in):
    r = client.post(PATH, json={}, headers=sign_in(make_person(name='Daniel Member')))
    assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})


def test_a_banned_address_is_refused_and_the_session_kept(client, codes, address):
    a = address()
    headers = _sign_in(client, codes, a)
    with api_tx() as tx:
        tx.execute("""INSERT INTO banned_person (normalized_email, ip_address, expires_at)
                      VALUES (%(e)s, '192.0.2.1', NOW() + INTERVAL '1 day')""", dict(e=a))
    r = client.post(PATH, json={}, headers=headers)
    assert (r.status_code, r.get_json()) == (403, {'error': 'refused'})
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM duo_session WHERE email = %(e)s', dict(e=a)).fetchone() is None
    assert client.get('/your-ahavah', headers=headers).status_code == 200


def test_closed_sign_ups_are_refused(client, codes, address, monkeypatch):
    import service.person as person
    headers = _sign_in(client, codes, address())
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', False)
    r = client.post(PATH, json={}, headers=headers)
    assert (r.status_code, r.get_json()) == (403, {'error': 'refused'})


def test_it_is_rate_limited_as_the_code_step(client, codes, address):
    """10 a minute from one network, as /your-ahavah/session."""
    answers = [client.post(PATH, json={}, headers={'X-Address-Token': 'z' * 43}).status_code for _ in range(11)]
    assert answers[:10] == [401] * 10 and answers[10] == 429
