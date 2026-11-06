"""Test accounts are kept apart from members (TEC-2135).

The owner, 6 Nov 2026: "i notice blaynes test user jess getting likes,
confusing people, i thought we had catered for the fact that people would
be testing by hiding those test accounts from the view of the actual app
users and only allowing those test accounts to interact with each other for
the purpose of testing".

A tester (roles holds 'tester') and a member who is not a tester never see
or reach each other; testers see testers, men women and women men; staff
who are not testers see everyone. What already exists across the line is
hidden, never deleted, and comes back when the role is revoked. Campaign
email and member counts leave testers out.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from database import api_tx
from service.testers import forget_tester_emails
from tests.unmatch_helpers import converse, match

_COUNTRY = 'XT'


@pytest.fixture(scope='module', autouse=True)
def _barrier_with_the_tester_rule():
    """tests/test_migration_0070.py re-applies 0070 mid-session, which
    redefines is_blocked_pair and is_deck_suppressed without the tester
    rule, and the suite shares one database. Apply 0095 again here, as the
    deploy leaves it: last."""
    path = Path(__file__).resolve().parent.parent / 'migrations' / '0095_tester_isolation.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


def _grant(person, *roles):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = %(r)s::TEXT[] WHERE id = %(i)s",
                   dict(i=person['id'], r=list(roles)))
    forget_tester_emails()


def _revoke(person):
    _grant(person)


@pytest.fixture
def world(make_person, add_photo, sign_in):
    """Two men and two women in their own country, on the map with a
    photo: Asher (a member), Jess (a tester), Miriam (a member) and Tobit
    (a tester)."""
    people = dict(
        asher=make_person(name='IsoAsher', gender='Man'),
        tobit=make_person(name='IsoTobit', gender='Man'),
        miriam=make_person(name='IsoMiriam', gender='Woman'),
        jess=make_person(name='IsoJess', gender='Woman'),
    )
    with api_tx() as tx:
        for p in people.values():
            tx.execute(
                """UPDATE person SET activated = TRUE, country = %(c)s,
                          show_my_location = TRUE, last_online_time = NOW(),
                          ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                         || '{"citySet": true}'::jsonb
                    WHERE id = %(i)s""",
                dict(c=_COUNTRY, i=p['id']))
            tx.execute("INSERT INTO search_preference_country (person_id, country) "
                       "VALUES (%(i)s, %(c)s) ON CONFLICT DO NOTHING",
                       dict(i=p['id'], c=_COUNTRY))
    for p in people.values():
        add_photo(p['id'])
    _grant(people['tobit'], 'tester')
    _grant(people['jess'], 'tester')
    people['headers'] = {k: sign_in(v) for k, v in people.items()}
    yield people
    # Every other row a test here writes goes with make_person's delete
    # (ON DELETE CASCADE). The inbox has no key to person, so its rows go
    # here, as in the unmatch tests; the suite shares one database.
    uuids = [people[k]['uuid'] for k in ('asher', 'tobit', 'miriam', 'jess')]
    with api_tx() as tx:
        tx.execute("DELETE FROM inbox WHERE luser = ANY(%(u)s) "
                   "OR split_part(remote_bare_jid, '@', 1) = ANY(%(u)s)", dict(u=uuids))
    forget_tester_emails()


def _h(w, who):
    return w['headers'][who]


def _deck(client, w, who, o=0, n=10):
    r = client.get(f'/search?n={n}&o={o}', headers=_h(w, who))
    assert r.status_code == 200, r.get_data(as_text=True)
    return {c['prospect_uuid'] for c in r.get_json()}


def _map(client, w, who):
    r = client.get('/map/markers', headers=_h(w, who))
    assert r.status_code == 200, r.get_data(as_text=True)
    return {m['uuid'] for m in r.get_json()['markers']}


def _profile_status(client, w, viewer, viewed):
    return client.get(f"/prospect-profile/{w[viewed]['uuid']}",
                      headers=_h(w, viewer)).status_code


def _uuids(w, *names):
    return {w[n]['uuid'] for n in names}


# ---------------------------------------------------------------------------
# The rule, in SQL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('a_roles,b_roles,split', [
    ([], [], False),
    (['tester'], ['tester'], False),
    (['tester'], [], True),
    ([], ['tester'], True),
    (['admin'], ['tester'], False),
    (['mod'], ['tester'], False),
    (['admin', 'tester'], [], True),
    (['mod', 'tester'], ['tester'], False),
])
def test_who_is_split(make_person, a_roles, b_roles, split):
    a, b = make_person(name='SplitA'), make_person(name='SplitB', gender='Woman')
    _grant(a, *a_roles)
    _grant(b, *b_roles)
    with api_tx() as tx:
        row = tx.execute(
            """SELECT is_tester_split_pair(%(a)s, %(b)s) AS ab,
                      is_tester_split_pair(%(b)s, %(a)s) AS ba,
                      is_blocked_pair(%(a)s, %(b)s) AS blocked,
                      is_deck_suppressed(%(a)s, %(b)s) AS deck""",
            dict(a=a['id'], b=b['id'])).fetchone()
    assert (row['ab'], row['ba'], row['blocked'], row['deck']) == (split,) * 4


# ---------------------------------------------------------------------------
# Discover, the map and profiles
# ---------------------------------------------------------------------------

def test_the_deck_shows_each_side_only_its_own(client, world):
    assert _deck(client, world, 'asher') == _uuids(world, 'miriam')
    assert _deck(client, world, 'miriam') == _uuids(world, 'asher')
    assert _deck(client, world, 'tobit') == _uuids(world, 'jess')
    assert _deck(client, world, 'jess') == _uuids(world, 'tobit')


def test_a_cached_deck_drops_someone_who_becomes_a_tester(client, world, make_person,
                                                          add_photo):
    _revoke(world['jess'])
    first = _deck(client, world, 'asher', o=0, n=1)
    assert first and first <= _uuids(world, 'miriam', 'jess')
    _grant(world['jess'], 'tester')
    # o > 0 reads the cache the first page wrote.
    assert world['jess']['uuid'] not in _deck(client, world, 'asher', o=1, n=10)


def test_the_map_shows_each_side_only_its_own(client, world):
    assert _map(client, world, 'asher') & _uuids(world, 'jess') == set()
    assert _map(client, world, 'jess') & _uuids(world, 'asher') == set()
    assert world['tobit']['uuid'] in _map(client, world, 'jess')
    assert world['jess']['uuid'] in _map(client, world, 'tobit')
    # Opposite gender only, testers included.
    assert world['tobit']['uuid'] not in _map(client, world, 'tobit')


@pytest.mark.parametrize('viewer,viewed', [('asher', 'jess'), ('jess', 'asher'),
                                           ('miriam', 'tobit'), ('tobit', 'miriam')])
def test_a_profile_across_the_line_is_not_found(client, world, viewer, viewed):
    assert _profile_status(client, world, viewer, viewed) == 404


def test_a_profile_across_the_line_records_no_view(client, world):
    _profile_status(client, world, 'asher', 'jess')
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM visited WHERE subject_person_id = %(a)s '
                          'AND object_person_id = %(b)s',
                          dict(a=world['asher']['id'], b=world['jess']['id'])).fetchone() is None


def test_testers_open_each_others_profiles(client, world):
    assert _profile_status(client, world, 'tobit', 'jess') == 200
    assert _profile_status(client, world, 'jess', 'tobit') == 200


@pytest.mark.parametrize('role', ['admin', 'mod'])
def test_staff_who_are_not_testers_see_both_sides(client, world, role):
    _grant(world['asher'], role)
    assert _profile_status(client, world, 'asher', 'jess') == 200
    assert _profile_status(client, world, 'asher', 'miriam') == 200


def test_staff_who_are_testers_are_testers(client, world):
    _grant(world['asher'], 'admin', 'tester')
    assert _profile_status(client, world, 'asher', 'miriam') == 404
    assert _profile_status(client, world, 'asher', 'jess') == 200


# ---------------------------------------------------------------------------
# Likes, matches, views and messages
# ---------------------------------------------------------------------------

def _incoming(client, w, who):
    r = client.get('/likes/incoming', headers=_h(w, who))
    assert r.status_code == 200
    return {l['with_profile']['id'] for l in r.get_json()['likes']}


def _outgoing(client, w, who):
    r = client.get('/likes/outgoing', headers=_h(w, who))
    assert r.status_code == 200
    return {l['with_profile']['id'] for l in r.get_json()['likes']}


def _matches(client, w, who):
    r = client.get('/matches', headers=_h(w, who))
    assert r.status_code == 200
    return {m['with_profile']['id'] for m in r.get_json()['matches']}


def _like(a, b):
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s) "
                   "ON CONFLICT DO NOTHING", dict(a=a['id'], b=b['id']))


def test_a_like_across_the_line_is_not_recorded(client, world):
    r = client.post('/decisions', json={'profile_uuid': world['jess']['uuid'],
                                        'decision': 'like'}, headers=_h(world, 'asher'))
    assert r.status_code == 200
    assert r.get_json() == {'match': None}
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM liked WHERE liker_id = %(a)s AND liked_id = %(b)s',
                          dict(a=world['asher']['id'], b=world['jess']['id'])).fetchone() is None


def test_a_like_between_testers_matches(client, world):
    _like(world['jess'], world['tobit'])
    r = client.post('/decisions', json={'profile_uuid': world['jess']['uuid'],
                                        'decision': 'like'}, headers=_h(world, 'tobit'))
    assert r.status_code == 200
    assert r.get_json()['match'] is not None


def test_a_super_like_across_the_line_is_not_found_and_costs_nothing(client, world):
    r = client.post('/tokens/super-like', json={'person_id': world['jess']['uuid']},
                    headers=_h(world, 'asher'))
    assert r.status_code == 404
    assert r.get_json() == {'error': 'not_available'}


def test_existing_likes_and_matches_disappear_from_both_sides_and_come_back(client, world):
    _like(world['jess'], world['asher'])      # Jess liked Asher
    _like(world['miriam'], world['tobit'])    # Miriam liked Tobit
    match(world['asher'], world['miriam'])    # members matched
    match(world['tobit'], world['jess'])      # testers matched

    assert world['jess']['uuid'] not in _incoming(client, world, 'asher')
    assert world['asher']['uuid'] not in _outgoing(client, world, 'jess')
    assert world['miriam']['uuid'] not in _outgoing(client, world, 'tobit') | \
        _incoming(client, world, 'tobit')
    assert world['tobit']['uuid'] not in _outgoing(client, world, 'miriam')
    assert _matches(client, world, 'asher') == _uuids(world, 'miriam')
    assert _matches(client, world, 'tobit') == _uuids(world, 'jess')

    # A cross match is hidden from both.
    match(world['asher'], world['jess'])
    assert world['jess']['uuid'] not in _matches(client, world, 'asher')
    assert world['asher']['uuid'] not in _matches(client, world, 'jess')

    # Nothing was deleted: revoking the role brings it back.
    _revoke(world['jess'])
    assert world['jess']['uuid'] in _matches(client, world, 'asher')
    with api_tx() as tx:
        assert tx.execute('SELECT count(*) AS n FROM liked WHERE liker_id = %(j)s',
                          dict(j=world['jess']['id'])).fetchone()['n'] >= 2


def _visitors(client, w, who):
    r = client.get('/visitors', headers=_h(w, who))
    assert r.status_code == 200
    j = r.get_json()
    return ({v['person_uuid'] for v in j['visited_you']},
            {v['person_uuid'] for v in j['you_visited']})


def test_existing_views_disappear_from_both_sides(client, world):
    with api_tx() as tx:
        for a, b in (('asher', 'jess'), ('tobit', 'jess'), ('asher', 'miriam')):
            tx.execute(
                """INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
                   VALUES (%(a)s, %(b)s, NOW(), FALSE) ON CONFLICT DO NOTHING""",
                dict(a=world[a]['id'], b=world[b]['id']))
    visited_you, _ = _visitors(client, world, 'jess')
    assert visited_you == _uuids(world, 'tobit')
    _, you_visited = _visitors(client, world, 'asher')
    assert you_visited == _uuids(world, 'miriam')


def test_conversations_across_the_line_are_hidden_from_both(world):
    from service.chat.chatutil import Q_IS_SKIPPED
    from service.chat.messagestorage.inbox import Q_GET_INBOX
    from service.chat.messagestorage.mam import Q_SELECT_MESSAGE

    converse(world['asher'], world['jess'], 'Shalom Jess')
    converse(world['tobit'], world['jess'], 'Shalom from a tester')

    def inbox(who):
        with api_tx() as tx:
            return {r['remote_bare_jid'].split('@')[0] for r in tx.execute(
                Q_GET_INBOX, dict(username=world[who]['uuid'])).fetchall()}

    def history(me, peer):
        with api_tx() as tx:
            return tx.execute(Q_SELECT_MESSAGE, dict(
                from_username=world[me]['uuid'], to_username=world[peer]['uuid'],
                before_id=None, max=50)).fetchall()

    assert inbox('jess') == _uuids(world, 'tobit')
    assert world['jess']['uuid'] not in inbox('asher')
    assert history('asher', 'jess') == []
    assert history('jess', 'asher') == []
    assert history('jess', 'tobit') != []

    with api_tx() as tx:
        gate = tx.execute(Q_IS_SKIPPED, dict(from_id=world['asher']['id'],
                                             to_id=world['jess']['id'])).fetchone()
    assert gate is not None, 'a message across the line is refused'

    _revoke(world['jess'])
    assert world['asher']['uuid'] in inbox('jess')


# ---------------------------------------------------------------------------
# Spotlight, Gatherings, campaign email and counts
# ---------------------------------------------------------------------------

def test_a_tester_is_never_eligible_for_spotlight(world):
    from service.spotlight.eligibility import eligibility
    with api_tx() as tx:
        ok, reason = eligibility(tx, world['jess']['id'])
    assert (ok, reason) == (False, 'staff')


def test_testers_are_left_out_of_campaign_email_and_counts(world):
    from service.admin.queries.members import counted_member_sql
    from service.growth.queries import _excluded

    with api_tx() as tx:
        jess_email = tx.execute('SELECT lower(email) AS e FROM person WHERE id = %(i)s',
                                dict(i=world['jess']['id'])).fetchone()['e']
        miriam_email = tx.execute('SELECT lower(email) AS e FROM person WHERE id = %(i)s',
                                  dict(i=world['miriam']['id'])).fetchone()['e']
    ex = _excluded()
    assert jess_email in ex
    assert miriam_email not in ex
    with api_tx() as tx:
        rows = {r['id']: r['counted'] for r in tx.execute(
            f"SELECT p.id, {counted_member_sql('p')} AS counted FROM person p "
            "WHERE p.id = ANY(%(i)s)",
            dict(i=[world['jess']['id'], world['miriam']['id']], ex=ex)).fetchall()}
    assert rows == {world['jess']['id']: False, world['miriam']['id']: True}


def test_a_gathering_organiser_sees_only_guests_on_their_own_side(world):
    from service.events.manage import guest_shown_sql
    with api_tx() as tx:
        visible = tx.execute(
            f"SELECT {guest_shown_sql('g', '%(org)s')} AS shown "
            "FROM (SELECT %(guest)s::int AS person_id) g",
            dict(org=world['asher']['id'], guest=world['jess']['id'])).fetchone()['shown']
        own = tx.execute(
            f"SELECT {guest_shown_sql('g', '%(org)s')} AS shown "
            "FROM (SELECT %(guest)s::int AS person_id) g",
            dict(org=world['asher']['id'], guest=world['miriam']['id'])).fetchone()['shown']
        no_member = tx.execute(
            f"SELECT {guest_shown_sql('g', 'NULL::int')} AS shown "
            "FROM (SELECT %(guest)s::int AS person_id) g",
            dict(guest=world['jess']['id'])).fetchone()['shown']
        no_account = tx.execute(
            f"SELECT {guest_shown_sql('g', '%(org)s')} AS shown "
            "FROM (SELECT NULL::int AS person_id) g",
            dict(org=world['asher']['id'])).fetchone()['shown']
    assert (visible, own, no_member, no_account) == (False, True, False, True)


# ---------------------------------------------------------------------------
# Granting the role
# ---------------------------------------------------------------------------

def _audit(uuid):
    with api_tx() as tx:
        return [dict(r['metadata']) for r in tx.execute(
            """SELECT metadata FROM admin_audit_log
                WHERE target_uuid = %(u)s::uuid AND action = 'patch_roles'
                ORDER BY created_at""", dict(u=uuid)).fetchall()]


def test_an_admin_grants_and_revokes_tester_with_an_audit_row(client, make_person,
                                                              admin_headers):
    p = make_person(name='GrantMe')
    try:
        r = client.patch(f"/admin/users/{p['uuid']}/roles",
                         json={'add': ['tester'], 'reason': 'Labs tester'},
                         headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['roles'] == ['tester']
        r = client.patch(f"/admin/users/{p['uuid']}/roles",
                         json={'remove': ['tester'], 'reason': 'Testing done'},
                         headers=admin_headers)
        assert r.get_json()['roles'] == []
        assert _audit(p['uuid']) == [
            {'before': [], 'after': ['tester'], 'reason': 'Labs tester'},
            {'before': ['tester'], 'after': [], 'reason': 'Testing done'},
        ]
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM admin_audit_log WHERE target_uuid = %(u)s::uuid',
                       dict(u=p['uuid']))


def test_the_users_list_filters_testers(client, make_person, admin_headers):
    p = make_person(name='FilterTester')
    q = make_person(name='FilterMember')
    _grant(p, 'tester')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['email']
    r = client.get('/admin/users?filters=role_tester&q=Filter', headers=admin_headers)
    assert r.status_code == 200
    uuids = {row.get('uuid') for row in r.get_json()['rows']}
    assert p['uuid'] in uuids and q['uuid'] not in uuids
    assert email


# ---------------------------------------------------------------------------
# Guard: the barrier keeps the rule
# ---------------------------------------------------------------------------

def test_the_latest_barrier_definitions_keep_the_tester_rule():
    """A later migration that redefines is_blocked_pair or
    is_deck_suppressed without is_tester_split_pair would quietly put
    testers back in front of members."""
    migrations = sorted((Path(__file__).resolve().parent.parent / 'migrations').glob('*.sql'))
    for fn in ('is_blocked_pair', 'is_deck_suppressed'):
        pattern = re.compile(
            rf'CREATE OR REPLACE FUNCTION {fn}\(.*?\$\$(.*?)\$\$', re.S | re.I)
        latest = None
        for path in migrations:
            for body in pattern.findall(path.read_text(encoding='utf-8')):
                latest = (path.name, body)
        assert latest is not None
        assert 'is_tester_split_pair' in latest[1], f'{fn} last defined in {latest[0]}'
