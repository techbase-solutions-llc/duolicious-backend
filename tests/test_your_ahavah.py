"""Your Ahavah, the light sign-in (TEC-1845; ahavah-web docs/plans/
2026-10-22-in-app-entry-and-sign-up.md, section 5 and release 4).

An address session, issued by a 6-digit code and kept apart from the
member's session and the half-finished sign-up record. It lists what is
held under the address and deletes all of it. It never opens a member
route and never shows a member's name (but a mentored single's first
name), photo or profile. Dark while light_sign_in or matchmaker_live is
off."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service import your_ahavah

pytestmark = pytest.mark.usefixtures('events_schema', 'matchmaker_schema', 'release_4_schema', 'events_live',
                                     'matchmaker_live', 'light_on', 'no_limits', 'mail_allowed')

NOW = datetime.now(timezone.utc)


@pytest.fixture
def light_on(monkeypatch, client):
    monkeypatch.setenv('AHAVAH_LIGHT_SIGN_IN_ENABLED', '1')
    # Not 127.0.0.1: other tests in the shared database ban that address,
    # and a banned network is answered as a send that never comes.
    client.environ_base['REMOTE_ADDR'] = '10.184.9.1'


@pytest.fixture
def codes(monkeypatch):
    """Every code the routes would mail, captured: [(email, code)]."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(your_ahavah, 'send_code', lambda email, code: sent.append((email, code)))
    return sent


@pytest.fixture
def address():
    made: list[str] = []

    def _make() -> str:
        a = f'light-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(a)
        return a

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM address_session WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM organiser WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM lead WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM mentor_account WHERE normalized_email = ANY(%(e)s)', dict(e=made))
        tx.execute('DELETE FROM tool_session WHERE owner_normalized_email = ANY(%(e)s)', dict(e=made))
        from service.matchmaker import address_key
        tx.execute('DELETE FROM recommendation WHERE sender_key = ANY(%(k)s)',
                   dict(k=[address_key(a) for a in made]))


def _sign_in(client, codes, email) -> dict:
    r = client.post('/your-ahavah/code', json=dict(email=email))
    assert r.status_code == 202, r.get_data(as_text=True)
    handle = r.get_json()['request_token']
    code = next(c for e, c in reversed(codes) if e == email)
    r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=code))
    assert r.status_code == 200, r.get_json()
    return {'X-Address-Token': r.get_json()['address_token']}


def _held(client, headers):
    r = client.get('/your-ahavah', headers=headers)
    assert r.status_code == 200, r.get_json()
    assert r.headers['Cache-Control'] == 'no-store'
    return r.get_json()


# ---------------------------------------------------------------------------
# Dark
# ---------------------------------------------------------------------------

_ROUTES = (('post', '/your-ahavah/code', dict(email='a@ahavah-test.invalid')),
           ('post', '/your-ahavah/session', dict(request_token='x' * 32, code='123456')),
           ('get', '/your-ahavah', None), ('post', '/your-ahavah/delete', None),
           ('delete', '/your-ahavah/session', None))


@pytest.mark.parametrize('off', ['AHAVAH_LIGHT_SIGN_IN_ENABLED', 'AHAVAH_MATCHMAKER_LIVE_ENABLED'])
def test_every_route_is_absent_while_a_switch_is_off(client, monkeypatch, codes, off):
    monkeypatch.delenv(off)
    for method, path, body in _ROUTES:
        r = getattr(client, method)(path, json=body, headers={'X-Address-Token': 'y' * 43})
        assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'}), (off, path)
    assert codes == []


def test_the_status_route_reports_the_switch(client, monkeypatch):
    assert client.get('/matchmaker/status').get_json()['light_sign_in'] is True
    monkeypatch.delenv('AHAVAH_LIGHT_SIGN_IN_ENABLED')
    assert client.get('/matchmaker/status').get_json()['light_sign_in'] is False
    monkeypatch.setenv('AHAVAH_LIGHT_SIGN_IN_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert client.get('/matchmaker/status').get_json()['light_sign_in'] is False


# ---------------------------------------------------------------------------
# The code
# ---------------------------------------------------------------------------

def test_every_request_gets_the_same_answer_and_only_a_real_one_is_mailed(client, codes, address, make_person,
                                                                         monkeypatch):
    nothing = address()
    member_address = address()
    make_person(name='Miriam Member', email=member_address)
    answers = [client.post('/your-ahavah/code', json=dict(email=e)) for e in (nothing, member_address)]
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: 'honeypot')
    refused = address()
    answers.append(client.post('/your-ahavah/code', json=dict(email=refused, website='bot')))
    answers.append(client.post('/your-ahavah/code', json=dict(email='not-an-address')))
    for r in answers:
        assert r.status_code == 202 and set(r.get_json()) == {'request_token'}
        assert r.headers['Cache-Control'] == 'no-store'
    assert [e for e, _ in codes] == [nothing, member_address]
    assert all(len(c) == 6 and c.isdigit() for _, c in codes)


def test_asking_for_a_code_never_touches_the_sign_up_record_or_a_member_session(client, codes, address):
    a = address()
    with api_tx() as tx:
        tx.execute("INSERT INTO onboardee (email, updated_at) VALUES (%(e)s, NOW() - INTERVAL '2 hours')",
                   dict(e=a))
    try:
        _sign_in(client, codes, a)
        with api_tx('read committed') as tx:
            assert tx.execute('SELECT 1 FROM onboardee WHERE email = %(e)s', dict(e=a)).fetchone() is not None
            assert tx.execute('SELECT 1 FROM duo_session WHERE email = %(e)s', dict(e=a)).fetchone() is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=a))


def test_a_wrong_code_is_counted_and_the_fifth_kills_it(client, codes, address):
    a = address()
    handle = client.post('/your-ahavah/code', json=dict(email=a)).get_json()['request_token']
    right = codes[-1][1]
    wrong = '000000' if right != '000000' else '111111'
    for _ in range(4):
        r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=wrong))
        assert (r.status_code, r.get_json()) == (401, {'error': 'wrong_code'})
    r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=wrong))
    assert r.get_json() == {'error': 'wrong_code'}
    r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=right))
    assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})


def test_a_code_works_once_and_lapses(client, codes, address):
    a = address()
    handle = client.post('/your-ahavah/code', json=dict(email=a)).get_json()['request_token']
    code = codes[-1][1]
    ok = client.post('/your-ahavah/session', json=dict(request_token=handle, code=code))
    assert ok.status_code == 200 and set(ok.get_json()) == {'address_token', 'expires_at'}
    again = client.post('/your-ahavah/session', json=dict(request_token=handle, code=code))
    assert (again.status_code, again.get_json()) == (401, {'error': 'expired'})
    handle = client.post('/your-ahavah/code', json=dict(email=a)).get_json()['request_token']
    with api_tx() as tx:
        tx.execute("UPDATE address_session SET code_expires_at = NOW() - INTERVAL '1 second' "
                   "WHERE request_token_hash = %(h)s", dict(h=hashlib.sha256(handle.encode()).hexdigest()))
    r = client.post('/your-ahavah/session', json=dict(request_token=handle, code=codes[-1][1]))
    assert r.get_json() == {'error': 'expired'}
    assert client.post('/your-ahavah/session', json=dict(request_token='z' * 32, code='123456')).get_json() \
        == {'error': 'expired'}


def test_a_handle_from_a_refused_request_matches_no_code(client, codes, address, monkeypatch):
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: 'stamp')
    handle = client.post('/your-ahavah/code', json=dict(email=address())).get_json()['request_token']
    for code in ('000000', '123456'):
        assert client.post('/your-ahavah/session', json=dict(request_token=handle, code=code)).get_json() \
            == {'error': 'expired'}


def test_the_session_lapses_after_an_hour(client, codes, address):
    a = address()
    headers = _sign_in(client, codes, a)
    with api_tx() as tx:
        tx.execute("UPDATE address_session SET session_expires_at = NOW() - INTERVAL '1 second' "
                   "WHERE normalized_email = %(e)s", dict(e=a))
    r = client.get('/your-ahavah', headers=headers)
    assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})


# ---------------------------------------------------------------------------
# Never a member session
# ---------------------------------------------------------------------------

_MEMBER_ROUTES = ('/app-entries/status', '/rsvp/mine', '/notifications/preferences', '/matchmaker/alert')


def test_the_address_token_opens_no_member_route(client, codes, address):
    headers = _sign_in(client, codes, address())
    token = headers['X-Address-Token']
    for path in _MEMBER_ROUTES:
        for h in ({'Authorization': f'Bearer {token}'}, headers):
            r = client.get(path, headers=h)
            assert r.status_code in (400, 401, 404), (path, h, r.status_code)


def test_a_member_session_does_not_open_your_ahavah(client, make_person, sign_in):
    p = make_person(name='Daniel Member')
    r = client.get('/your-ahavah', headers=sign_in(p))
    assert (r.status_code, r.get_json()) == (401, {'error': 'expired'})


# ---------------------------------------------------------------------------
# What the address holds
# ---------------------------------------------------------------------------

def _hold_everything(a, *, published, confirmed_guest, make_person):
    """Something in every section, plus what must never show."""
    from service.leads import confirm_lead, record_lead
    from service.leads.sources import ALERT_VISITOR
    from service.matchmaker import address_key
    out = {}
    with api_tx() as tx:
        out['organiser'] = tx.execute(
            """INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at)
               VALUES ('Grace Fellowship', 'fellowship_leader', %(e)s, %(e)s, NOW(), NOW()) RETURNING id""",
            dict(e=a)).fetchone()['id']
    hosted = published(dict(id=out['organiser']), venue='14 Elm Street, Dallas')
    confirmed_guest(hosted, name='Hannah Okafor', party_size=2)
    out['hosted'] = hosted
    going_to = published(venue='22 Oak Road, Austin')
    out['place'] = confirmed_guest(going_to, email=a, name='Ruth Sender')
    out['going_to'] = going_to
    single = make_person(name='Rivka Levi', gender='Woman')
    out['single'] = single
    recipient = f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
    with api_tx() as tx:
        acc = tx.execute('INSERT INTO mentor_account (email, normalized_email) VALUES (%(e)s, %(e)s) RETURNING id',
                         dict(e=a)).fetchone()['id']
        tx.execute("""INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, relation,
                                               mentor_account_id, invite_expires_at, confirmed_at)
                      VALUES (%(s)s, %(e)s, %(e)s, 'parent', %(a)s, NOW() + interval '14 days', NOW())""",
                   dict(s=single['id'], e=a, a=acc))
        sid = tx.execute(
            """INSERT INTO tool_session (kind, mode, source, owner_email, owner_normalized_email, owner_display,
                                         claimed_at, completed_at)
               VALUES ('game', 'us', 'tool:game-us', %(e)s, %(e)s, 'Ruth', NOW(), NOW()) RETURNING id, uuid::text""",
            dict(e=a)).fetchone()
        tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, display, finished_at)
                      VALUES (%(s)s, 'guest', %(h)s, 'Jonathan Secret', NOW())""",
                   dict(s=sid['id'], h=uuid4().hex))
        tx.execute("INSERT INTO tool_result (session_id, score, breakdown) VALUES (%(s)s, 72, '{}')",
                   dict(s=sid['id']))
        out['session'] = sid['uuid']
        lead = record_lead(tx, email=a, source=ALERT_VISITOR)
        confirm_lead(tx, lead, 'link')
        tx.execute("""INSERT INTO match_alert (lead_id, first_name, criteria, confirmed_at)
                      VALUES (%(l)s, 'Ruth', %(c)s::jsonb, NOW())""",
                   dict(l=lead, c=json.dumps(dict(age_min=25, age_max=35, region='europe'))))
        for status, rk in (('sent', address_key(recipient)), ('queued', address_key('x' + recipient))):
            tx.execute("""INSERT INTO recommendation (sender_key, sender_first_name, recipient_email, recipient_key,
                                                      note, status)
                          VALUES (%(k)s, 'Ruth', %(r)s, %(rk)s, 'You would like it', %(s)s)""",
                       dict(k=address_key(a), r=recipient, rk=rk, s=status))
    out['recipient'] = recipient
    return out


def test_it_lists_what_the_address_holds_and_nothing_of_anyone_else(client, codes, address, published,
                                                                    confirmed_guest, make_person):
    a = address()
    held = _hold_everything(a, published=published, confirmed_guest=confirmed_guest, make_person=make_person)
    out = _held(client, _sign_in(client, codes, a))
    assert out['email'] == a and out['member'] is False and out['empty'] is False
    assert out['organiser'] == dict(name='Grace Fellowship', approved=True)
    (g,) = out['hosting']
    assert (g['slug'], g['status'], g['going'], g['ended']) == (held['hosted'], 'published', 2, False)
    (p,) = out['places']
    assert (p['slug'], p['state'], p['party_size'], p['cancelled']) == (held['going_to'], 'going', 1, False)
    assert out['mentoring'] == [dict(first_name='Rivka', relation='parent', since=out['mentoring'][0]['since'],
                                     conversations_shared=0)]
    (res,) = out['results']
    assert (res['session_id'], res['mode'], res['seat'], res['completed'], res['result']) == \
        (held['session'], 'us', 'owner', True, dict(score=72))
    assert (out['alert']['confirmed'], out['alert']['age_min'], out['alert']['region']) == (True, 25, 'europe')
    assert out['recommendations'] == [dict(date=NOW.date().isoformat(), count=2)]
    text = json.dumps(out)
    for secret in ('Hannah', 'Okafor', 'Elm Street', 'Oak Road', 'Levi', 'Jonathan', held['recipient'],
                   'You would like it', 'photo', 'uuid'):
        assert secret not in text, secret


def test_a_mentored_single_says_how_many_conversations_they_share(client, codes, single_with_mentor,
                                                                   introducer_with_two):
    """Copy 2.1: "Sharing {n} conversation with you". The count of what the
    mentor can open now: a live share, on this link, with someone the
    single is still matched with. Never a name or a word of it."""
    from service.matchmaker import mentors
    single, samuel, _, _ = single_with_mentor()
    daniel = introducer_with_two.member('Daniel Stone', 'Man', 'Woman')
    gone = introducer_with_two.member('Jonathan Gone', 'Man', 'Woman')
    stopped = introducer_with_two.member('Aaron Stopped', 'Man', 'Woman')
    for other in (daniel, gone, stopped):
        introducer_with_two.match(single, other)
    try:
        headers = _sign_in(client, codes, single['mentor_email'])
        assert _held(client, headers)['mentoring'][0]['conversations_shared'] == 0
        with api_tx() as tx:
            mentors.share(tx, single['id'], samuel['uuid'])
        (m,) = _held(client, headers)['mentoring']
        assert m['conversations_shared'] == 1
        with api_tx() as tx:
            for other in (daniel, gone, stopped):
                mentors.share(tx, single['id'], other['uuid'])
            mentors.unshare(tx, single['id'], stopped['uuid'])
            # Unmatched after the share: the mentor can no longer open it.
            tx.execute('DELETE FROM ahavah_match WHERE %(g)s IN (user_a_id, user_b_id)', dict(g=gone['id']))
        out = _held(client, headers)
        (m,) = out['mentoring']
        assert m['conversations_shared'] == 2
        text = json.dumps(out)
        for secret in ('Samuel', 'Stone', 'Daniel', 'Jonathan', 'Aaron', samuel['uuid'], daniel['uuid']):
            assert secret not in text, secret
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM address_session WHERE normalized_email = %(e)s', dict(e=single['mentor_email']))


def test_an_address_that_holds_nothing_gets_the_same_shape_empty(client, codes, address, published,
                                                                 confirmed_guest, make_person):
    full_address = address()
    _hold_everything(full_address, published=published, confirmed_guest=confirmed_guest, make_person=make_person)
    full = _held(client, _sign_in(client, codes, full_address))
    empty = _held(client, _sign_in(client, codes, address()))
    assert set(empty) == set(full)
    assert (empty['organiser'], empty['alert']) == (None, None)
    for key in ('hosting', 'places', 'mentoring', 'results', 'recommendations'):
        assert empty[key] == [], key
    assert empty['empty'] is True and empty['member'] is False


def test_ahavahs_own_organiser_is_not_listed(client, codes, address, published):
    a = address()
    with api_tx() as tx:
        oid = tx.execute("""INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at)
                            VALUES ('Ahavah', 'ahavah', %(e)s, %(e)s, NOW(), NOW()) RETURNING id""",
                         dict(e=a)).fetchone()['id']
    published(dict(id=oid))
    out = _held(client, _sign_in(client, codes, a))
    assert out['organiser'] is None and out['hosting'] == []


# ---------------------------------------------------------------------------
# Delete everything
# ---------------------------------------------------------------------------

def _count(sql, **params) -> int:
    with api_tx('read committed') as tx:
        return tx.execute(f'SELECT count(*)::int AS n FROM ({sql}) x', params).fetchone()['n']


def test_delete_removes_exactly_what_the_address_holds(client, codes, address, published, confirmed_guest,
                                                       make_person):
    from service.matchmaker import address_key
    a = address()
    held = _hold_everything(a, published=published, confirmed_guest=confirmed_guest, make_person=make_person)
    other = address()
    others = _hold_everything(other, published=published, confirmed_guest=confirmed_guest, make_person=make_person)
    with api_tx() as tx:
        tx.execute("INSERT INTO waitlist_signup (email) VALUES (%(e)s) ON CONFLICT DO NOTHING", dict(e=a))
    headers = _sign_in(client, codes, a)
    r = client.post('/your-ahavah/delete', headers=headers)
    assert (r.status_code, r.get_json()) == (200, {'deleted': True})

    def holds(ne):
        k = address_key(ne)
        return dict(
            organiser=_count('SELECT 1 FROM organiser WHERE normalized_email = %(e)s', e=ne),
            places=_count('SELECT 1 FROM event_rsvp WHERE normalized_email = %(e)s', e=ne),
            mentor=_count('SELECT 1 FROM mentor_account WHERE normalized_email = %(e)s', e=ne)
            + _count('SELECT 1 FROM mentor_link WHERE mentor_normalized_email = %(e)s', e=ne),
            results=_count('SELECT 1 FROM tool_session WHERE owner_normalized_email = %(e)s', e=ne),
            leads=_count('SELECT 1 FROM lead WHERE normalized_email = %(e)s', e=ne),
            recommendations=_count('SELECT 1 FROM recommendation WHERE sender_key = %(k)s', k=k),
            sessions=_count('SELECT 1 FROM address_session WHERE normalized_email = %(e)s', e=ne),
            waitlist=_count('SELECT 1 FROM waitlist_signup WHERE email = %(e)s', e=ne))

    assert set(holds(a).values()) == {0}, holds(a)
    left = holds(other)
    assert all(left[k] for k in ('organiser', 'places', 'mentor', 'results', 'leads', 'recommendations')), left
    # The hosted gathering went with its guests; the other address's stays.
    assert _count('SELECT 1 FROM event WHERE slug = %(s)s', s=held['hosted']) == 0
    assert _count('SELECT 1 FROM event WHERE slug = %(s)s', s=others['hosted']) == 1
    # A sent recommendation keeps its row for the single's sake, with no
    # trace of the sender.
    assert _count("SELECT 1 FROM recommendation WHERE sender_key LIKE 'deleted:%%' AND recipient_key = %(k)s",
                  k=address_key(held['recipient'])) == 1
    # The session ended with it.
    assert client.get('/your-ahavah', headers=headers).get_json() == {'error': 'expired'}


def test_delete_also_takes_a_half_finished_sign_up(client, codes, address):
    a = address()
    with api_tx() as tx:
        tx.execute('INSERT INTO onboardee (email) VALUES (%(e)s)', dict(e=a))
        tx.execute("""INSERT INTO onboardee_photo (email, position, uuid, blurhash, hash)
                      VALUES (%(e)s, 1, %(u)s, 'b', 'h')""", dict(e=a, u=f'light-{uuid4().hex}'))
        tx.execute("INSERT INTO duo_session (session_token_hash, email, otp) VALUES (%(h)s, %(e)s, '123456')",
                   dict(h=uuid4().hex, e=a))
    r = client.post('/your-ahavah/delete', headers=_sign_in(client, codes, a))
    assert r.status_code == 200
    assert _count('SELECT 1 FROM onboardee WHERE email = %(e)s', e=a) == 0
    assert _count('SELECT 1 FROM duo_session WHERE email = %(e)s', e=a) == 0


def test_a_members_address_cannot_be_emptied_here(client, codes, address, make_person, published, confirmed_guest):
    a = address()
    make_person(name='Miriam Member', email=a)
    rid = confirmed_guest(published(), email=a)['id']
    headers = _sign_in(client, codes, a)
    assert _held(client, headers)['member'] is True
    r = client.post('/your-ahavah/delete', headers=headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'member'})
    assert _count('SELECT 1 FROM event_rsvp WHERE id = %(i)s', i=rid) == 1


def test_starting_a_profile_with_the_same_address_brings_it_across(client, codes, address, published,
                                                                  confirmed_guest, make_person, finish_onboarding):
    """"Start a matchmaking profile" is the web's sign-up with the address
    filled in. The finish-sign-up steps that already exist bring across the
    confirmed leads, the saved Together results, the confirmed RSVPs and a
    confirmed visitor alert. Organisers, mentors and recommendations sent
    are matched by address when needed, so they need no step."""
    a = address()
    held = _hold_everything(a, published=published, confirmed_guest=confirmed_guest, make_person=make_person)
    r, pid = finish_onboarding(email=a)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT person_id FROM event_rsvp WHERE id = %(i)s',
                          dict(i=held['place']['id'])).fetchone()['person_id'] == pid
        assert tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s::uuid',
                          dict(u=held['session'])).fetchone()['owner_person_id'] == pid
        assert tx.execute('SELECT 1 FROM match_alert WHERE person_id = %(p)s', dict(p=pid)).fetchone()
        assert tx.execute('SELECT count(*)::int AS n FROM lead WHERE normalized_email = %(e)s AND person_id IS NULL',
                          dict(e=a)).fetchone()['n'] == 0
    # The address now belongs to a member: Your Ahavah says so and will not
    # empty it.
    assert _held(client, _sign_in(client, codes, a))['member'] is True


def test_signing_out_ends_the_session(client, codes, address):
    headers = _sign_in(client, codes, address())
    assert client.delete('/your-ahavah/session', headers=headers).status_code == 200
    assert client.get('/your-ahavah', headers=headers).get_json() == {'error': 'expired'}


def test_the_sweep_deletes_lapsed_rows_address_and_all(address):
    a = address()
    with api_tx() as tx:
        tx.execute("""INSERT INTO address_session (email, normalized_email, request_token_hash, code_expires_at,
                                                   session_expires_at)
                      VALUES (%(e)s, %(e)s, %(h)s, NOW() - INTERVAL '3 days', NOW() - INTERVAL '2 days')""",
                   dict(e=a, h=uuid4().hex))
        tx.execute("""INSERT INTO address_session (email, normalized_email, request_token_hash, code_expires_at,
                                                   session_expires_at)
                      VALUES (%(e)s, %(e)s, %(h)s, NOW() - INTERVAL '3 days', NOW() + INTERVAL '10 minutes')""",
                   dict(e=a, h=uuid4().hex))
        assert your_ahavah.purge(tx) >= 1
    assert _count('SELECT 1 FROM address_session WHERE normalized_email = %(e)s', e=a) == 1
