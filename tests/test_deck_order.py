"""The deck shows members seen in the last 30 days first (health review,
13 Oct 2026, finding 33).

The deck sorted on verification first, so a verified member who left two
months ago came before an unverified member who was here yesterday, and new
likes went to people who would not see them: 8 of 18 likes in the week of
5 Oct went to members offline 30 days or more. Members away longer stay in
the deck (owner decision, 1 Oct 2026), after everyone seen recently. Paid
boosts stay on top.

The order is fixed when the first page builds the member's search cache;
later pages read the cache in that order, so both paths are tested.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx

# A user-assigned ISO code no real member has, so the deck under test holds
# only this test's people, whatever else the shared database contains.
_COUNTRY = 'XQ'


@pytest.fixture
def deck(make_person):
    searcher = make_person(name='DeckSearcher', gender='Man')
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
            (hashlib.sha512(tok.encode()).hexdigest(), f'deck-{searcher["id"]}@example.com',
             searcher['id']))

    def prospect(name: str, *, days_offline: int, verification_level: int = 1) -> str:
        p = make_person(name=name, gender='Woman')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET activated = TRUE, country = %(c)s,
                          last_online_time = NOW() - make_interval(days => %(d)s),
                          verification_level_id = %(v)s
                    WHERE id = %(i)s""",
                dict(c=_COUNTRY, d=days_offline, v=verification_level, i=p['id']))
        return p['uuid']

    return dict(headers={'Authorization': f'Bearer {tok}'}, prospect=prospect)


def _page(client, headers, n: int, o: int) -> list[str]:
    r = client.get(f'/search?n={n}&o={o}', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return [row['prospect_uuid'] for row in r.get_json()]


def test_members_seen_in_the_last_30_days_come_first(client, deck):
    away_verified = deck['prospect']('AwayVerified', days_offline=60, verification_level=2)
    recent = deck['prospect']('Recent', days_offline=3)
    recent_older = deck['prospect']('RecentOlder', days_offline=20)

    assert _page(client, deck['headers'], 10, 0) == [recent, recent_older, away_verified]


def test_a_boost_still_comes_first(client, deck):
    recent = deck['prospect']('RecentUnboosted', days_offline=1)
    boosted = deck['prospect']('Boosted', days_offline=2)
    with api_tx() as tx:
        tx.execute("INSERT INTO active_boosts (person_id, started_at, expires_at) "
                   "VALUES (%(p)s, NOW(), NOW() + interval '30 minutes')", dict(p=boosted))

    assert _page(client, deck['headers'], 10, 0) == [boosted, recent]


def test_the_next_page_keeps_the_order(client, deck):
    """Ten verified members away for 40 days and two unverified members
    seen this week: the two lead page one, and page two (read from the
    cache) holds the last of the away members."""
    away = [deck['prospect'](f'Away{i}', days_offline=40 + i, verification_level=2)
            for i in range(10)]
    recent = [deck['prospect'](f'Here{i}', days_offline=1 + i) for i in range(2)]

    first = _page(client, deck['headers'], 10, 0)
    second = _page(client, deck['headers'], 10, 10)

    assert first == recent + away[:8]
    assert second == away[8:]
