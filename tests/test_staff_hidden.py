"""Staff are hidden from members (TEC-2040, the owner, 11 Nov 2026).

An account whose roles hold 'admin' or 'mod' never appears to a member
anywhere members see people: Discover, the map, a profile by link, Views,
Liked you, You liked, Matches, the inbox and chat, the matchmaker, Spotlight
and gathering guest lists. Staff still see everyone. A staff account that is
also a tester stays a tester (TEC-2135 decides). What already exists between
a member and a staff account is hidden from the member, never deleted, and
no new like or match is made across the line.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from database import api_tx
from tests.unmatch_helpers import converse, match

_COUNTRY = 'XS'
_MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


@pytest.fixture(scope='module', autouse=True)
def _barrier_with_the_staff_rule():
    """Other modules re-apply 0070 and 0095 mid-session, which redefine
    is_deck_suppressed without the staff rule, and the suite shares one
    database. Apply 0099 again here, as the deploy leaves it: last."""
    with api_tx() as tx:
        tx.execute((_MIGRATIONS / '0099_staff_hidden.sql').read_text(encoding='utf-8'))


def _roles(person, *roles):
    with api_tx() as tx:
        tx.execute('UPDATE person SET roles = %(r)s::TEXT[] WHERE id = %(i)s',
                   dict(i=person['id'], r=list(roles)))
    from service.testers import forget_tester_emails
    forget_tester_emails()


@pytest.fixture
def world(make_person, add_photo, sign_in):
    """Asher (a member) and Abel (an admin), men; Miriam (a member), Dora
    (an admin) and Mona (a moderator), women. All on the map with a photo,
    in their own country."""
    people = dict(
        asher=make_person(name='StfAsher', gender='Man'),
        abel=make_person(name='StfAbel', gender='Man'),
        miriam=make_person(name='StfMiriam', gender='Woman'),
        dora=make_person(name='StfDora', gender='Woman'),
        mona=make_person(name='StfMona', gender='Woman'),
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
        # Who viewed you is Premium (TEC-2070): read the full rows.
        tx.execute("UPDATE person SET entitlements = ARRAY['premium'] WHERE id = ANY(%(i)s)",
                   dict(i=[people['asher']['id'], people['abel']['id']]))
    for p in people.values():
        add_photo(p['id'])
    _roles(people['abel'], 'admin')
    _roles(people['dora'], 'admin')
    _roles(people['mona'], 'mod')
    people['h'] = {k: sign_in(v) for k, v in people.items()}
    yield people
    uuids = [people[k]['uuid'] for k in ('asher', 'abel', 'miriam', 'dora', 'mona')]
    with api_tx() as tx:
        tx.execute("DELETE FROM inbox WHERE luser = ANY(%(u)s) "
                   "OR split_part(remote_bare_jid, '@', 1) = ANY(%(u)s)", dict(u=uuids))


def _uuids(w, *names):
    return {w[n]['uuid'] for n in names}


def _get(client, w, who, path):
    r = client.get(path, headers=w['h'][who])
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('viewer_roles,other_roles,hidden', [
    ([], ['admin'], True),
    ([], ['mod'], True),
    ([], [], False),
    (['admin'], [], False),
    (['mod'], ['admin'], False),
    (['tester'], ['admin'], True),
    ([], ['admin', 'tester'], False),
])
def test_who_is_hidden(make_person, viewer_roles, other_roles, hidden):
    v, o = make_person(name='HidV'), make_person(name='HidO', gender='Woman')
    _roles(v, *viewer_roles)
    _roles(o, *other_roles)
    with api_tx() as tx:
        row = tx.execute('SELECT is_staff_hidden(%(v)s, %(o)s) AS h, '
                         'is_staff_hidden(NULL, %(o)s) AS anon',
                         dict(v=v['id'], o=o['id'])).fetchone()
    assert row['h'] is hidden
    assert row['anon'] is (bool(set(other_roles) & {'admin', 'mod'}) and 'tester' not in other_roles)


def test_the_latest_deck_barrier_keeps_the_staff_rule():
    pattern = re.compile(r'CREATE OR REPLACE FUNCTION is_deck_suppressed\(.*?\$\$(.*?)\$\$', re.S | re.I)
    latest = None
    for path in sorted(_MIGRATIONS.glob('*.sql')):
        for body in pattern.findall(path.read_text(encoding='utf-8')):
            latest = (path.name, body)
    assert latest is not None
    assert 'is_staff_hidden' in latest[1], f'is_deck_suppressed last defined in {latest[0]}'
    assert 'is_tester_split_pair' in latest[1], f'is_deck_suppressed last defined in {latest[0]}'


# ---------------------------------------------------------------------------
# Discover, the map and profiles
# ---------------------------------------------------------------------------

def _deck(client, w, who, o=0, n=10):
    return {c['prospect_uuid'] for c in _get(client, w, who, f'/search?n={n}&o={o}')}


def _map(client, w, who):
    return {m['uuid'] for m in _get(client, w, who, '/map/markers')['markers']}


def test_a_member_never_sees_staff_in_the_deck_or_on_the_map(client, world):
    assert _deck(client, world, 'asher') == _uuids(world, 'miriam')
    assert _map(client, world, 'asher') & _uuids(world, 'dora', 'mona') == set()
    assert world['miriam']['uuid'] in _map(client, world, 'asher')


def test_staff_still_see_members(client, world):
    assert _deck(client, world, 'abel') >= _uuids(world, 'miriam')
    assert world['miriam']['uuid'] in _map(client, world, 'abel')
    assert client.get(f"/prospect-profile/{world['miriam']['uuid']}",
                      headers=world['h']['abel']).status_code == 200


def test_a_cached_deck_drops_someone_made_staff(client, world):
    _roles(world['dora'])
    first = _deck(client, world, 'asher', o=0, n=1)
    assert first <= _uuids(world, 'miriam', 'dora')
    _roles(world['dora'], 'admin')
    assert world['dora']['uuid'] not in _deck(client, world, 'asher', o=1, n=10)


@pytest.mark.parametrize('staff', ['dora', 'mona'])
def test_a_staff_profile_is_not_found_by_a_member(client, world, staff):
    for path in ('/prospect-profile/', '/conversation-prospect/'):
        assert client.get(path + world[staff]['uuid'],
                          headers=world['h']['asher']).status_code == 404
    # Nor by a visitor with no session, even when public.
    with api_tx() as tx:
        tx.execute('UPDATE person SET public_profile = TRUE WHERE id = %(i)s',
                   dict(i=world[staff]['id']))
    assert client.get('/prospect-profile/' + world[staff]['uuid']).status_code == 404


def test_a_staff_tester_stays_a_tester(client, world):
    _roles(world['dora'], 'admin', 'tester')
    _roles(world['abel'], 'tester')
    assert client.get(f"/prospect-profile/{world['dora']['uuid']}",
                      headers=world['h']['asher']).status_code == 404
    assert client.get(f"/prospect-profile/{world['dora']['uuid']}",
                      headers=world['h']['abel']).status_code == 200


# ---------------------------------------------------------------------------
# Likes, matches, views and messages
# ---------------------------------------------------------------------------

def test_no_like_or_super_like_crosses_the_staff_line(client, world):
    from service.tokens import credit
    for who, whom in (('asher', 'dora'), ('abel', 'miriam')):
        r = client.post('/decisions', json={'profile_uuid': world[whom]['uuid'], 'decision': 'like'},
                        headers=world['h'][who])
        assert r.status_code == 200 and r.get_json() == {'match': None}
        with api_tx() as tx:
            credit(tx, world[who]['uuid'], 5, reason='purchase', metadata={})
        r = client.post('/tokens/super-like', json={'person_id': world[whom]['uuid']},
                        headers=world['h'][who])
        assert r.status_code == 404
    with api_tx() as tx:
        assert tx.execute('SELECT 1 FROM liked WHERE (liker_id, liked_id) IN '
                          '((%(a)s, %(d)s), (%(b)s, %(m)s))',
                          dict(a=world['asher']['id'], d=world['dora']['id'],
                               b=world['abel']['id'], m=world['miriam']['id'])).fetchone() is None


def test_existing_likes_matches_and_views_are_hidden_from_the_member_only(client, world):
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(m)s, %(a)s)',
                   dict(m=world['mona']['id'], a=world['asher']['id']))
        tx.execute("""INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
                      VALUES (%(d)s, %(a)s, NOW(), FALSE), (%(m)s, %(b)s, NOW(), FALSE)""",
                   dict(d=world['dora']['id'], a=world['asher']['id'],
                        m=world['miriam']['id'], b=world['abel']['id']))
    match(world['asher'], world['dora'])
    incoming = {l['with_profile']['id'] for l in _get(client, world, 'asher', '/likes/incoming')['likes']}
    outgoing = {l['with_profile']['id'] for l in _get(client, world, 'asher', '/likes/outgoing')['likes']}
    matches = {m['with_profile']['id'] for m in _get(client, world, 'asher', '/matches')['matches']}
    visited_you = {v['person_uuid'] for v in _get(client, world, 'asher', '/visitors')['visited_you']}
    assert (incoming | outgoing | matches | visited_you) & _uuids(world, 'dora', 'mona') == set()
    # Staff still see theirs, and nothing was deleted.
    assert world['asher']['uuid'] in {m['with_profile']['id']
                                      for m in _get(client, world, 'dora', '/matches')['matches']}
    assert world['miriam']['uuid'] in {v['person_uuid']
                                       for v in _get(client, world, 'abel', '/visitors')['visited_you']}
    _roles(world['dora'])
    assert world['dora']['uuid'] in {m['with_profile']['id']
                                     for m in _get(client, world, 'asher', '/matches')['matches']}


def test_a_conversation_with_staff_is_hidden_from_the_member(world):
    from service.chat.chatutil import Q_IS_SKIPPED
    from service.chat.messagestorage.inbox import Q_GET_INBOX
    from service.chat.messagestorage.mam import Q_SELECT_MESSAGE
    from service.person.sql import Q_INBOX_INFO

    converse(world['dora'], world['asher'], 'Shalom from staff')

    def inbox(who):
        with api_tx() as tx:
            return {r['remote_bare_jid'].split('@')[0] for r in tx.execute(
                Q_GET_INBOX, dict(username=world[who]['uuid'])).fetchall()}

    with api_tx() as tx:
        history = tx.execute(Q_SELECT_MESSAGE, dict(
            from_username=world['asher']['uuid'], to_username=world['dora']['uuid'],
            before_id=None, max=50)).fetchall()
        gates = [tx.execute(Q_IS_SKIPPED, dict(from_id=world[a]['id'], to_id=world[b]['id'])).fetchone()
                 for a, b in (('asher', 'dora'), ('dora', 'asher'))]
        info = [r for r in tx.execute(Q_INBOX_INFO, dict(person_id=world['asher']['id'])).fetchall()
                if str(r['person_uuid']) == world['dora']['uuid']]
    assert world['dora']['uuid'] not in inbox('asher')
    assert world['asher']['uuid'] in inbox('dora')
    assert history == []
    assert all(g is not None for g in gates)
    assert [r['name'] for r in info] in ([], [None])


# ---------------------------------------------------------------------------
# Matchmaker, Spotlight and Gatherings
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures('matchmaker_schema')
def test_the_matchmaker_never_offers_staff_to_a_member(world):
    from service.matchmaker.introductions import visible_sql
    match(world['asher'], world['dora'])
    match(world['asher'], world['miriam'])
    with api_tx() as tx:
        seen = {r['uuid'] for r in tx.execute(
            f"SELECT p.uuid::text AS uuid FROM person p WHERE {visible_sql('%(me)s')}",
            dict(me=world['asher']['id'])).fetchall()}
    assert world['miriam']['uuid'] in seen
    assert world['dora']['uuid'] not in seen


@pytest.mark.parametrize('staff', ['dora', 'mona'])
def test_staff_are_never_eligible_for_spotlight(world, staff):
    from service.spotlight.eligibility import eligibility
    with api_tx() as tx:
        ok, reason = eligibility(tx, world[staff]['id'])
    assert (ok, reason) == (False, 'staff')


def test_a_gathering_organiser_member_does_not_see_staff_guests(world):
    from service.events.manage import guest_shown_sql

    def shown(org, guest):
        with api_tx() as tx:
            return tx.execute(
                f"SELECT {guest_shown_sql('g', '%(org)s::int')} AS shown "
                "FROM (SELECT %(guest)s::int AS person_id) g",
                dict(org=org, guest=guest)).fetchone()['shown']

    assert shown(world['asher']['id'], world['mona']['id']) is False
    assert shown(None, world['mona']['id']) is False
    assert shown(world['asher']['id'], world['miriam']['id']) is True
    assert shown(world['abel']['id'], world['mona']['id']) is True


# ---------------------------------------------------------------------------
# Member-facing counts
# ---------------------------------------------------------------------------

def test_a_moderator_is_not_a_new_member_in_the_roundup(make_person):
    from service.spotlight.roundup import roundup_totals
    mod = make_person(name='RoundupMod')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE, country = 'TV' WHERE id = %(i)s",
                   dict(i=mod['id']))
        before = roundup_totals(tx)
        tx.execute("UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s",
                   dict(i=mod['id']))
        after = roundup_totals(tx)
    assert after['count'] == before['count'] - 1
    assert 'Tuvalu' not in after['country_names']


def test_a_moderator_is_not_a_newcomer_to_a_member(world):
    from datetime import datetime, timedelta, timezone

    from service.growth.queries import count_all_newcomers_since, count_newcomers_since
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    me = world['asher']['id']
    with api_tx() as tx:
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=me))
        fit = count_newcomers_since(tx, me, since)
        anyone = count_all_newcomers_since(tx, me, since)
    _roles(world['mona'])
    with api_tx() as tx:
        assert count_newcomers_since(tx, me, since) == fit + 1
        assert count_all_newcomers_since(tx, me, since) == anyone + 1
