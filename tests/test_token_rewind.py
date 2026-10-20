"""Discover Rewind (2026-05-19) — POST /tokens/rewind spend path tests.

Mirrors tests/test_token_boost.py: real person rows inserted in a fixture,
cleanup via explicit DELETE. Rewind undoes a PASS (a `skipped` row) for a
token; likes are out of scope.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from service.tokens import credit, get_balance, InsufficientTokens
from service.tokens.actions.rewind import perform as perform_rewind, NothingToRewind


def _make_person(tx):
    return tx.execute(
        """
        INSERT INTO person (
            email, normalized_email, name, date_of_birth,
            coordinates, gender_id, about, location_short_friendly, location_long_friendly, unit_id
        )
        VALUES (
            %(email)s, %(email)s, 'Test', '1990-01-01',
            ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography,
            (SELECT id FROM gender LIMIT 1),
            'about', 'somewhere', 'somewhere, nowhere', (SELECT id FROM unit LIMIT 1)
        )
        RETURNING uuid::text AS uuid, id
        """,
        dict(email=f'rewind-{uuid4()}@example.com'),
    ).fetchone()


@pytest.fixture
def pair():
    """A (me, prospect) pair of real person rows."""
    from database import api_tx
    with api_tx() as tx:
        me = _make_person(tx)
        prospect = _make_person(tx)
    yield {'me': me, 'prospect': prospect}
    with api_tx() as tx:
        tx.execute(
            "DELETE FROM person WHERE id = ANY(%s)",
            ([me['id'], prospect['id']],),
        )


def _skip(tx, me, prospect):
    tx.execute(
        "INSERT INTO skipped (subject_person_id, object_person_id) "
        "VALUES (%(s)s, %(o)s)",
        dict(s=me['id'], o=prospect['id']),
    )


def _skip_exists(tx, me, prospect) -> bool:
    return bool(tx.execute(
        "SELECT 1 FROM skipped WHERE subject_person_id = %(s)s "
        "AND object_person_id = %(o)s",
        dict(s=me['id'], o=prospect['id']),
    ).fetchone())


def _cache_row(tx, me, prospect, position=0):
    tx.execute(
        """
        INSERT INTO search_cache (
            searcher_person_id, position, prospect_person_id, prospect_uuid,
            name, match_percentage, personality
        )
        VALUES (
            %(s)s, %(pos)s, %(p)s, %(pu)s,
            'Test', 0,
            ('[' || array_to_string(array_fill(0, ARRAY[47]), ',') || ']')::vector
        )
        """,
        dict(s=me['id'], pos=position, p=prospect['id'], pu=prospect['uuid']),
    )


def _cache_row_exists(tx, me, prospect) -> bool:
    return bool(tx.execute(
        "SELECT 1 FROM search_cache WHERE searcher_person_id = %(s)s "
        "AND prospect_person_id = %(p)s",
        dict(s=me['id'], p=prospect['id']),
    ).fetchone())


def test_rewind_debits_1_and_deletes_skip(pair):
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _skip(tx, me, prospect)
        result = perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        assert result == {'rewound': True, 'profile_uuid': prospect['uuid']}
        assert get_balance(tx, me['uuid']) == 4
        assert not _skip_exists(tx, me, prospect)


def test_rewind_with_no_skip_raises_and_does_not_debit(pair):
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        with pytest.raises(NothingToRewind):
            perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        # Existence check runs before the debit — balance untouched.
        assert get_balance(tx, me['uuid']) == 5


def test_rewind_clears_search_cache_row_for_pair(pair):
    """F9: rewind must clear the pair's search_cache row so the paid-back
    profile can reappear inside the current cached deck session (see-passes
    and take-back-like already do this)."""
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _skip(tx, me, prospect)
        _cache_row(tx, me, prospect)
        assert _cache_row_exists(tx, me, prospect)
        perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        assert not _cache_row_exists(tx, me, prospect)


def test_rewind_insufficient_tokens_keeps_skip(pair):
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        _skip(tx, me, prospect)  # balance is 0 — no credit
        with pytest.raises(InsufficientTokens):
            perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        # Debit raises before the deletes, so the skip survives.
        assert _skip_exists(tx, me, prospect)
        assert get_balance(tx, me['uuid']) == 0


# A report is permanent (migration 0035): a rewind undoes a pass, never a
# report, from either side of the pair, and spends nothing when refused.

def _report(tx, subject, obj):
    tx.execute(
        "INSERT INTO skipped (subject_person_id, object_person_id, "
        "reported, report_reason) VALUES (%(s)s, %(o)s, TRUE, 'test') "
        "ON CONFLICT (subject_person_id, object_person_id) "
        "DO UPDATE SET reported = TRUE, report_reason = 'test'",
        dict(s=subject['id'], o=obj['id']),
    )


def _is_reported(tx, subject, obj) -> bool:
    return bool(tx.execute(
        "SELECT 1 FROM skipped WHERE subject_person_id = %(s)s "
        "AND object_person_id = %(o)s AND reported",
        dict(s=subject['id'], o=obj['id']),
    ).fetchone())


def test_rewind_never_undoes_my_own_report(pair):
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _report(tx, me, prospect)
        _cache_row(tx, me, prospect)
        with pytest.raises(NothingToRewind):
            perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        assert _is_reported(tx, me, prospect)
        assert get_balance(tx, me['uuid']) == 5


def test_rewind_never_undoes_a_pass_i_later_reported(pair):
    """A pass escalated to a report is the same row, now reported."""
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _skip(tx, me, prospect)
        _report(tx, me, prospect)
        with pytest.raises(NothingToRewind):
            perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        assert _is_reported(tx, me, prospect)
        assert get_balance(tx, me['uuid']) == 5


def test_rewind_refused_when_they_reported_me(pair):
    """My pass of someone who reported me: the report hides the pair for
    good, so a rewind could not bring them back. Refused before the debit,
    and both rows stay."""
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _skip(tx, me, prospect)
        _report(tx, prospect, me)
        with pytest.raises(NothingToRewind):
            perform_rewind(tx, me['uuid'], me['id'], prospect['uuid'])
        assert _skip_exists(tx, me, prospect)
        assert _is_reported(tx, prospect, me)
        assert get_balance(tx, me['uuid']) == 5


def test_reported_person_cannot_rewind_the_report_against_them(pair):
    """The reported person has no pass of their own: nothing to rewind,
    and the reporter's row is untouched."""
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, prospect['uuid'], 5, reason='purchase', metadata={})
        _report(tx, me, prospect)
        with pytest.raises(NothingToRewind):
            perform_rewind(tx, prospect['uuid'], prospect['id'], me['uuid'])
        assert _is_reported(tx, me, prospect)
        assert get_balance(tx, prospect['uuid']) == 5


def test_rewind_route_refuses_a_report(pair, client, sign_in):
    """POST /tokens/rewind answers 409 nothing_to_rewind for a report,
    the same answer as no pass at all, and spends nothing."""
    from database import api_tx
    me, prospect = pair['me'], pair['prospect']
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
        _report(tx, me, prospect)
    res = client.post(
        '/tokens/rewind', headers=sign_in(me),
        json={'profile_uuid': prospect['uuid']},
    )
    assert res.status_code == 409
    assert res.get_json() == {'error': 'nothing_to_rewind'}
    with api_tx() as tx:
        assert _is_reported(tx, me, prospect)
        assert get_balance(tx, me['uuid']) == 5
