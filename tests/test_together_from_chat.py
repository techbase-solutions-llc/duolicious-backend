"""Together from a chat and a member's past results (TEC-1845; ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, sections 3 and 5,
release 4).

POST /tools/chat-sessions starts the marriage checklist (or the Us game)
with a match, attached to the chat and saved to the member from the start,
as "Play Us together" is. Only the match can take the seat, and no share
token is issued (owner decision 5). GET /tools/mine lists the member's
finished games and checklists, the ones saved with their address before
they joined included. Both answer 404 unless Together is live and
app_entries lets the member in."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema', 'release_4_schema', 'together_live', 'no_limits',
                                     'entries_on')


@pytest.fixture
def entries_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')


@pytest.fixture(autouse=True)
def _forget_sessions():
    yield
    with api_tx() as tx:
        tx.execute("DELETE FROM tool_session WHERE owner_email LIKE '%%@chat-test.invalid' "
                   "OR owner_normalized_email LIKE '%%@chat-test.invalid'")


@pytest.fixture
def pair(make_person, sign_in):
    """pair(matched=True) -> (her, him, her headers, his headers): an
    activated woman and man, matched unless asked otherwise."""
    def _member(name, gender):
        p = make_person(name=name, gender=gender, email=f'{name.split()[0].lower()}-{uuid4().hex[:8]}@chat-test.invalid')
        with api_tx() as tx:
            tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=p['id']))
        return p

    def _make(matched: bool = True, his_gender: str = 'Man'):
        her = _member('Miriam Cohen', 'Woman')
        him = _member('Daniel Stone', his_gender)
        if matched:
            with api_tx() as tx:
                tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                           'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                           dict(a=her['id'], b=him['id']))
        return her, him, sign_in(her), sign_in(him)

    return _make


def _start(client, headers, with_uuid, kind='checklist', **body):
    return client.post('/tools/chat-sessions', json=dict(kind=kind, with_uuid=with_uuid, **body), headers=headers)


def _p(importance, stance='agree'):
    return dict(section='biblical', importance=importance, stance=stance)


# ---------------------------------------------------------------------------
# Dark
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('env,value', [('AHAVAH_TOGETHER_LIVE_ENABLED', None), ('AHAVAH_APP_ENTRIES', 'off'),
                                       ('AHAVAH_APP_ENTRIES', 'owner')])
def test_both_routes_are_absent_until_together_and_the_entries_let_the_member_in(client, pair, monkeypatch,
                                                                                 env, value):
    her, him, h, _ = pair()
    if value is None:
        monkeypatch.delenv(env)
    else:
        monkeypatch.setenv(env, value)
    r = _start(client, h, him['uuid'])
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})
    r = client.get('/tools/mine', headers=h)
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})


def test_owner_only_lets_the_listed_member_in(client, pair, monkeypatch):
    her, him, h, _ = pair()
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', str(her['id']))
    assert _start(client, h, him['uuid']).status_code == 201
    assert client.get('/tools/mine', headers=h).status_code == 200


def test_members_only(client, pair, tool_visitor):
    her, him, _, _ = pair()
    _, visitor = tool_visitor()
    for headers in ({}, visitor):
        assert _start(client, headers, him['uuid']).status_code in (400, 401)
        assert client.get('/tools/mine', headers=headers).status_code in (400, 401)


# ---------------------------------------------------------------------------
# Starting with a match
# ---------------------------------------------------------------------------

def test_the_checklist_starts_saved_with_the_chat_attached_and_no_share(client, pair):
    her, him, h, _ = pair()
    r = _start(client, h, him['uuid'])
    assert r.status_code == 201, r.get_json()
    out = r.get_json()
    assert set(out) == {'session_id', 'player_token', 'invite_token', 'view'}
    v = out['view']
    assert (v['kind'], v['mode'], v['seat'], v['role'], v['state']) == ('checklist', 'couple', 'owner', 'wife',
                                                                         'playing')
    assert (v['claimed'], v['member'], v['my_display'], v['share_token']) == (True, True, 'Miriam', None)
    assert v['invite_token'] == out['invite_token']
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT chat_person_id, owner_person_id, share_token FROM tool_session '
                         'WHERE uuid = %(u)s::uuid', dict(u=out['session_id'])).fetchone()
    assert (row['chat_person_id'], row['owner_person_id'], row['share_token']) == (him['id'], her['id'], None)


def test_the_us_game_starts_the_same_way(client, pair):
    her, him, _, h = pair()
    r = _start(client, h, her['uuid'], kind='game', display='Dan')
    assert r.status_code == 201
    v = r.get_json()['view']
    assert (v['kind'], v['mode'], v['role'], v['my_display']) == ('game', 'us', None, 'Dan')


@pytest.mark.parametrize('case', ['unmatched', 'same_gender', 'unknown', 'not_a_uuid', 'self', 'reported',
                                  'leaving'])
def test_only_with_a_match(client, pair, case):
    her, him, h, _ = pair(matched=case != 'unmatched', his_gender='Woman' if case == 'same_gender' else 'Man')
    target = him['uuid']
    if case == 'unknown':
        target = str(uuid4())
    elif case == 'not_a_uuid':
        target = 'nobody'
    elif case == 'self':
        target = her['uuid']
    elif case == 'reported':
        with api_tx() as tx:
            tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported)
                          VALUES (%(a)s, %(b)s, TRUE)""", dict(a=him['id'], b=her['id']))
    elif case == 'leaving':
        with api_tx() as tx:
            tx.execute('UPDATE person SET deletion_requested_at = NOW() WHERE id = %(i)s', dict(i=him['id']))
    r = _start(client, h, target)
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'}), case


def test_only_the_match_can_take_the_seat_and_both_see_the_comparison(client, pair, make_person, sign_in):
    her, him, h_her, h_him = pair()
    out = _start(client, h_her, him['uuid']).get_json()
    invite = out['invite_token']
    stranger = make_person(name='Someone Else', gender='Man')
    for headers in ({}, sign_in(stranger)):
        r = client.post(f'/tools/i/{invite}/players', json=dict(display='Intruder'), headers=headers)
        assert (r.status_code, r.get_json()) == (409, {'error': 'full'})
    r = client.post(f'/tools/i/{invite}/players', json=dict(display='Daniel'), headers=h_him)
    assert r.status_code == 201, r.get_json()
    guest = r.get_json()
    sid = out['session_id']
    for token, role in ((out['player_token'], 'wife'), (guest['player_token'], 'husband')):
        r = client.post(f'/tools/sessions/{sid}/answers', headers={'X-Tool-Token': token},
                        json=dict(role=role, answers=[dict(question_key='p1', answer=_p(5))]))
        assert r.status_code == 200, r.get_json()
        assert client.post(f'/tools/sessions/{sid}/finish', headers={'X-Tool-Token': token}).status_code == 200
    for headers in (h_her, h_him):
        v = client.get(f'/tools/sessions/{sid}', headers=headers).get_json()
        assert v['state'] == 'ready' and v['result'] is not None and v['share_token'] is None


# ---------------------------------------------------------------------------
# Past results
# ---------------------------------------------------------------------------

def _session(*, mode='us', kind='game', owner_person=None, owner_email=None, claimed=True, completed=True,
             chat_person=None, owner_finished='NOW()', score=None):
    with api_tx() as tx:
        s = tx.execute(
            f"""INSERT INTO tool_session (kind, mode, source, owner_person_id, owner_email, owner_normalized_email,
                                          owner_display, claimed_at, completed_at, chat_person_id)
                VALUES (%(k)s, %(m)s, %(src)s, %(p)s, %(e)s, %(e)s, 'Owner',
                        {'NOW()' if claimed else 'NULL'}, {'NOW()' if completed else 'NULL'}, %(c)s)
                RETURNING id, uuid::text AS uuid""",
            dict(k=kind, m=mode, src={'us': 'tool:game-us', 'me': 'tool:game-me', 'couple': 'tool:checklist',
                                      'single': 'tool:checklist', 'knows_me': 'tool:knows-me'}[mode],
                 p=owner_person, e=owner_email, c=chat_person)).fetchone()
        tx.execute(f"""INSERT INTO tool_player (session_id, seat, token_hash, finished_at)
                       VALUES (%(s)s, 'owner', %(h)s, {owner_finished})""", dict(s=s['id'], h=uuid4().hex))
        if score is not None:
            tx.execute("INSERT INTO tool_result (session_id, score, breakdown) VALUES (%(s)s, %(v)s, '{}')",
                       dict(s=s['id'], v=score))
    return s


def _guest(session, *, person=None, email=None, display='Guest', finished=True):
    with api_tx() as tx:
        tx.execute(f"""INSERT INTO tool_player (session_id, seat, token_hash, display, person_id, email,
                                                normalized_email, finished_at)
                       VALUES (%(s)s, 'guest', %(h)s, %(d)s, %(p)s, %(e)s, %(e)s,
                               {'NOW()' if finished else 'NULL'})""",
                   dict(s=session['id'], h=uuid4().hex, d=display, p=person, e=email))


def test_the_members_results_with_those_saved_before_joining(client, pair, make_person):
    her, him, h, _ = pair()
    with api_tx() as tx:
        her_email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=her['id'])).fetchone()['email']
    owned = _session(owner_person=her['id'], owner_email=her_email, score=81, chat_person=him['id'],
                     owner_finished="NOW() - INTERVAL '3 days'")
    _guest(owned, person=him['id'], display='Daniel')
    before_joining = _session(mode='me', owner_email=her_email, owner_finished="NOW() - INTERVAL '30 days'")
    as_guest = _session(mode='couple', kind='checklist', owner_email='someone@chat-test.invalid',
                        owner_finished="NOW() - INTERVAL '2 days'", completed=False)
    _guest(as_guest, email=her_email, display='Miriam')
    # Not hers: unfinished, deleted, unsaved before joining, someone else's.
    _session(owner_person=her['id'], owner_email=her_email, owner_finished='NULL')
    gone = _session(owner_person=her['id'], owner_email=her_email)
    with api_tx() as tx:
        tx.execute('UPDATE tool_session SET deleted_at = NOW() WHERE id = %(i)s', dict(i=gone['id']))
    _session(owner_email=her_email, claimed=False)
    _session(owner_person=him['id'], owner_email='daniel@chat-test.invalid')
    r = client.get('/tools/mine', headers=h)
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    out = r.get_json()
    ids = [x['session_id'] for x in out['results']]
    assert ids == [as_guest['uuid'], owned['uuid'], before_joining['uuid']]
    by_id = {x['session_id']: x for x in out['results']}
    o = by_id[owned['uuid']]
    assert (o['mode'], o['seat'], o['state'], o['result'], o['other_display'], o['with_uuid']) == \
        ('us', 'owner', 'ready', dict(score=81), 'Daniel', him['uuid'])
    g = by_id[as_guest['uuid']]
    assert (g['seat'], g['state'], g['result'], g['other_display'], g['with_uuid']) == \
        ('guest', 'waiting', None, 'Owner', None)
    assert by_id[before_joining['uuid']]['seat'] == 'owner'
    assert out['more'] is False


def test_the_match_sees_the_chat_game_from_their_side(client, pair):
    her, him, _, h_him = pair()
    s = _session(owner_person=her['id'], owner_email='m@chat-test.invalid', score=64, chat_person=him['id'])
    _guest(s, person=him['id'], display='Daniel')
    (x,) = [r for r in client.get('/tools/mine', headers=h_him).get_json()['results'] if r['session_id'] == s['uuid']]
    assert (x['seat'], x['with_uuid'], x['other_display'], x['result']) == ('guest', her['uuid'], 'Owner',
                                                                            dict(score=64))


def test_an_empty_list(client, pair):
    _, _, h, _ = pair()
    assert client.get('/tools/mine', headers=h).get_json() == dict(results=[], more=False)
