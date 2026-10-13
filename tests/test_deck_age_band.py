"""With no age filter from the client, the member's saved age band ranks the
deck (health review, 13 Oct 2026, finding 34).

`search_preference_age` is computed for every member at sign-up (own age
plus or minus 2 and a fifth of the years past 18) and search never read it,
so the deck opened on everyone from 18 to 80: women passed 195 of 284 men
outside their band and liked 20 of 30 inside it.

The first fix used the band as a filter, and on production data that left
9 of 40 active members with an empty deck. The band is now a ranking:
members inside it come before members outside it, and nobody is removed
for age. It sits after a paid boost and before "seen in the last 30 days".
A bound the client sends (either one alone counts) is a hard filter and
the band plays no part. The band is clamped to the web slider's 18 to 80,
an open bound stays open, and a member with no band (or a band whose
bounds cross) gets no ranking from it.
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
def deck(client, make_person):
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
                       "VALUES (%(i)s, %(lo)s, %(hi)s) "
                       "ON CONFLICT (person_id) DO UPDATE "
                       "SET min_age = EXCLUDED.min_age, max_age = EXCLUDED.max_age",
                       dict(i=searcher['id'], lo=min_age, hi=max_age))

    def no_band() -> None:
        with api_tx() as tx:
            tx.execute("DELETE FROM search_preference_age WHERE person_id = %(i)s",
                       dict(i=searcher['id']))

    def aged(age: int, *, days_offline: int = 1) -> str:
        p = make_person(name=f'Aged{age}', gender='Woman')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET activated = TRUE, country = %(c)s,
                          last_online_time = NOW() - make_interval(days => %(d)s),
                          date_of_birth = (CURRENT_DATE - make_interval(years => %(a)s)
                                           - interval '30 days')::date
                    WHERE id = %(i)s""", dict(c=_COUNTRY, a=age, d=days_offline, i=p['id']))
            # The deck shows members with an approved photo only (finding 95).
            tx.execute(
                "INSERT INTO photo (uuid, person_id, position, blurhash, hash, nsfw_score, "
                "moderation_status, face_count) VALUES (md5(random()::text) || md5(random()::text), "
                "%(i)s, 1, 'b', md5(random()::text), 0.01, 'approved', 1)", dict(i=p['id']))
        return p['uuid']

    def page(query: str = '', n: int = 10, o: int = 0) -> list[str]:
        r = client.get(f'/search?n={n}&o={o}{query}', headers={'Authorization': f'Bearer {tok}'})
        assert r.status_code == 200, r.get_data(as_text=True)
        return [row['prospect_uuid'] for row in r.get_json()]

    return dict(band=band, no_band=no_band, aged=aged, page=page)


@pytest.fixture
def people(deck):
    return {age: deck['aged'](age) for age in (19, 25, 35, 45, 85)}


def _uuids(people, ages):
    return {people[a] for a in ages}


def test_out_of_band_members_still_appear_after_in_band_ones(deck, people):
    deck['band'](30, 40)
    shown = deck['page']()
    assert set(shown) == set(people.values())
    assert shown[0] == people[35]


def test_the_band_comes_before_seen_recently(deck):
    """An in-band member away for 60 days still leads an out-of-band
    member seen yesterday."""
    deck['band'](30, 40)
    away_in_band = deck['aged'](35, days_offline=60)
    recent_out = deck['aged'](55, days_offline=1)
    assert deck['page']() == [away_in_band, recent_out]


def test_a_boost_still_comes_before_the_band(deck):
    deck['band'](30, 40)
    in_band = deck['aged'](35)
    boosted_out = deck['aged'](55)
    with api_tx() as tx:
        tx.execute("INSERT INTO active_boosts (person_id, started_at, expires_at) "
                   "VALUES (%(p)s, NOW(), NOW() + interval '30 minutes')", dict(p=boosted_out))
    assert deck['page']() == [boosted_out, in_band]


def test_a_client_filter_still_filters(deck, people):
    deck['band'](30, 40)
    assert set(deck['page']('&age_min=18&age_max=80')) == _uuids(people, (19, 25, 35, 45))


def test_one_bound_from_the_client_is_a_client_filter(deck, people):
    deck['band'](30, 40)
    assert set(deck['page']('&age_min=40')) == _uuids(people, (45, 85))
    assert set(deck['page']('&age_max=30')) == _uuids(people, (19, 25))


def test_a_member_with_no_band_sees_everyone(deck, people):
    assert set(deck['page']()) == set(people.values())


def test_an_open_bound_stays_open(deck, people):
    deck['band'](None, 40)
    shown = deck['page']()
    assert set(shown) == set(people.values())
    assert set(shown[:3]) == _uuids(people, (19, 25, 35))


def test_the_band_is_clamped_to_the_slider(deck, people):
    deck['band'](10, 95)
    shown = deck['page']()
    assert set(shown[:4]) == _uuids(people, (19, 25, 35, 45))
    assert shown[4] == people[85]


def test_a_crossed_band_has_no_ranking_effect(deck, people):
    deck['band'](50, 40)
    crossed = deck['page']()
    deck['no_band']()
    assert crossed == deck['page']()
    assert set(crossed) == set(people.values())


def test_the_next_page_keeps_the_order(deck):
    """Ten out-of-band members seen this week and two in-band members away
    for 40 days: the two lead page one, and page two (read from the cache)
    holds the last of the out-of-band members."""
    deck['band'](30, 40)
    out = [deck['aged'](55, days_offline=1 + i) for i in range(10)]
    in_band = [deck['aged'](35, days_offline=40 + i) for i in range(2)]

    first = deck['page'](n=10, o=0)
    second = deck['page'](n=10, o=10)

    assert first == in_band + out[:8]
    assert second == out[8:]
