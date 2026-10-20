"""An unmatch is for good (TEC-1845, migration 0070): neither person sees the
other in Discover or on the map, and no like, super-like or reaction reaches
across it. Both likes outlive the unmatch, so each way back is pinned here."""
from __future__ import annotations

import pytest

from database import api_tx
from service.search.sql import (
    Q_CACHED_SEARCH,
    Q_MAP_MARKERS,
    Q_UNCACHED_SEARCH_1,
    Q_UNCACHED_SEARCH_2,
)
from service.tokens import credit, get_balance
from tests.unmatch_helpers import counts, match

pytestmark = pytest.mark.usefixtures('no_limits')

# Mirrored from tests/test_deck_gates.py, with n raised to the build's own
# LIMIT 1000 so the read returns the whole deck the build made.
DECK_PARAMS = dict(
    n=1000, o=0,
    verified_only=False,
    intents=[], marital_statuses=[], has_children_buckets=[],
    assemblies=[], torah_levels=[], polygyny_stances=[], calendars=[],
    educations=[], health_tags=[],
    age_min=None, age_max=None,
    band_min=None, band_max=None,
    local_radius_m=160_000,
    photo_gate=False,
)


def _deck(tx, searcher: dict) -> set[str]:
    p = dict(DECK_PARAMS, searcher_person_id=searcher['id'], gender_preference=[])
    tx.execute(Q_UNCACHED_SEARCH_1, p)
    tx.execute(Q_UNCACHED_SEARCH_2, p)
    return {str(r['prospect_uuid']) for r in tx.execute(Q_CACHED_SEARCH, p).fetchall()}


def _map(tx, viewer: dict) -> set[str]:
    rows = tx.execute(Q_MAP_MARKERS, dict(
        searcher_person_id=viewer['id'], gender_preference=[], photo_gate=False)).fetchall()
    return {str(r['uuid']) for r in rows}


def _shown_everywhere(add_photo, *people) -> None:
    """An approved photo and a city: what the deck and the map ask of a member."""
    for person in people:
        add_photo(person['id'])
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET ahavah_extra = jsonb_set(
                       COALESCE(ahavah_extra, '{}'::jsonb), '{citySet}', 'true'::jsonb)
                    WHERE id = %(p)s""", dict(p=person['id']))


def _unmatch(client, p) -> None:
    assert client.post(f'/unmatch/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200


def test_neither_sees_the_other_in_discover_or_on_the_map(client, unmatch_pair, make_person, add_photo):
    p = unmatch_pair
    control = make_person(name='Control', gender='Woman')
    _shown_everywhere(add_photo, p.a, p.b, control)
    match(p.a, p.b)
    _unmatch(client, p)
    with api_tx() as tx:
        # The likes alone would keep them out of each other's deck. Take both
        # back, as /likes/outgoing/take-back allows once the match row is
        # gone, so the unmatch is all that is left to do it.
        tx.execute(
            """DELETE FROM liked WHERE liker_id IN (%(a)s, %(b)s) AND liked_id IN (%(a)s, %(b)s)""",
            dict(a=p.a['id'], b=p.b['id']))
        assert control['uuid'] in _deck(tx, p.b), 'the deck shows a member it should'
        assert control['uuid'] in _map(tx, p.b), 'the map shows a member it should'
        assert p.b['uuid'] not in _deck(tx, p.a)
        assert p.a['uuid'] not in _deck(tx, p.b)
        assert p.b['uuid'] not in _map(tx, p.a)
        assert p.a['uuid'] not in _map(tx, p.b)


def test_a_like_cannot_make_the_match_again(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)
    like = dict(profile_uuid=p.a['uuid'], decision='like')

    # Both likes still stand, so without the guard this re-matches at once.
    assert client.post('/decisions', json=like, headers=p.b_headers).get_json() == {'match': None}
    with api_tx() as tx:
        tx.execute('DELETE FROM liked WHERE liker_id = %(b)s AND liked_id = %(a)s',
                   dict(a=p.a['id'], b=p.b['id']))
    assert client.post('/decisions', json=like, headers=p.b_headers).get_json() == {'match': None}

    with api_tx('read committed') as tx:
        relike = tx.execute('SELECT count(*) AS n FROM liked WHERE liker_id = %(b)s AND liked_id = %(a)s',
                            dict(a=p.a['id'], b=p.b['id'])).fetchone()['n']
    assert relike == 0
    assert counts(p.a, p.b)['matches'] == 0


def test_a_super_like_is_refused_and_charges_nothing(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)
    with api_tx() as tx:
        credit(tx, p.b['uuid'], 5, reason='purchase', metadata={})

    r = client.post('/tokens/super-like', json={'person_id': p.a['uuid']}, headers=p.b_headers)

    assert (r.status_code, r.get_json()) == (404, {'error': 'not_available'})
    with api_tx('read committed') as tx:
        assert get_balance(tx, p.b['uuid']) == 5
    assert counts(p.a, p.b)['matches'] == 0


def test_a_reaction_cannot_reach_across(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)

    r = client.post('/messages/stanza-after/reactions', json={'peer_uuid': p.a['uuid']},
                    headers=p.b_headers)

    assert (r.status_code, r.get_json()) == (403, {'error': 'not_allowed'})
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM message_reactions WHERE reactor_id = %(b)s',
                       dict(b=p.b['id'])).fetchone()['n']
    assert n == 0
