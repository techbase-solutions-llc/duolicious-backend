"""With no age filter from the client, the deck uses the member's saved age
band (health review, 13 Oct 2026, finding 34).

`search_preference_age` is computed for every member at sign-up (own age
plus or minus 2 and a fifth of the years past 18) and search never read it,
so the deck opened on everyone from 18 to 80: women passed 195 of 284 men
outside their band and liked 20 of 30 inside it. Now the band is the
default. A filter the client sends wins, either bound alone counts as one,
the band is clamped to the web slider's 18 to 80, an open bound stays open,
and a member with no band (or a band that cannot match anyone) sees
everyone, as every other filter fails open.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx

# A user-assigned ISO code no real member has: the deck holds only this
# test's people (tests/test_deck_order.py uses XQ).
_COUNTRY = 'XR'


@pytest.fixture
def deck(make_person):
    searcher = make_person(name='BandSearcher', gender='Man')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = %(i)s", dict(i=searcher['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=searcher['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) "
                   "VALUES (%(i)s, %(c)s)", dict(i=searcher['id'], c=_COUNTRY))
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%s, %s, %s, TRUE, '123456')""",
            (hashlib.sha512(tok.encode()).hexdigest(), f'band-{searcher["id"]}@example.com',
             searcher['id']))

    def band(min_age, max_age) -> None:
        with api_tx() as tx:
            tx.execute("INSERT INTO search_preference_age (person_id, min_age, max_age) "
                       "VALUES (%(i)s, %(lo)s, %(hi)s)",
                       dict(i=searcher['id'], lo=min_age, hi=max_age))

    def aged(age: int) -> str:
        p = make_person(name=f'Aged{age}', gender='Woman')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET activated = TRUE, country = %(c)s,
                          date_of_birth = (CURRENT_DATE - make_interval(years => %(a)s)
                                           - interval '30 days')::date
                    WHERE id = %(i)s""", dict(c=_COUNTRY, a=age, i=p['id']))
            # The deck shows members with an approved photo only (finding 95).
            tx.execute(
                "INSERT INTO photo (uuid, person_id, position, blurhash, hash, nsfw_score, "
                "moderation_status, face_count) VALUES (md5(random()::text) || md5(random()::text), "
                "%(i)s, 1, 'b', md5(random()::text), 0.01, 'approved', 1)", dict(i=p['id']))
        return p['uuid']

    def ages_seen(query: str = '') -> set[str]:
        r = client_ref[0].get(f'/search?n=10&o=0{query}', headers={'Authorization': f'Bearer {tok}'})
        assert r.status_code == 200, r.get_data(as_text=True)
        return {row['prospect_uuid'] for row in r.get_json()}

    client_ref: list = []
    return dict(band=band, aged=aged, seen=ages_seen, client_ref=client_ref)


@pytest.fixture
def people(client, deck):
    deck['client_ref'].append(client)
    return {age: deck['aged'](age) for age in (19, 25, 35, 45, 85)}


def test_no_client_filter_uses_the_saved_band(deck, people):
    deck['band'](30, 40)
    assert deck['seen']() == {people[35]}


def test_a_client_filter_wins_over_the_band(deck, people):
    deck['band'](30, 40)
    assert deck['seen']('&age_min=18&age_max=80') == {people[a] for a in (19, 25, 35, 45)}


def test_one_bound_from_the_client_is_a_client_filter(deck, people):
    deck['band'](30, 40)
    assert deck['seen']('&age_min=40') == {people[45], people[85]}


def test_a_member_with_no_band_sees_everyone(deck, people):
    assert deck['seen']() == set(people.values())


def test_an_open_bound_stays_open(deck, people):
    deck['band'](None, 40)
    assert deck['seen']() == {people[a] for a in (19, 25, 35)}


def test_the_band_is_clamped_to_the_slider(deck, people):
    deck['band'](10, 95)
    assert deck['seen']() == {people[a] for a in (19, 25, 35, 45)}


def test_a_band_that_cannot_match_fails_open(deck, people):
    deck['band'](50, 40)
    assert deck['seen']() == set(people.values())
