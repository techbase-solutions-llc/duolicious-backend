"""The SQL fragments the deck and the matchmaker's alerts share (TEC-1845).

The alerts count new members who fit with the deck's own clauses, so an
alert can never say someone fits whom the deck would not show. Moving the
clauses into service/search/predicates.py must not change what the deck
means: the deck query's text, whitespace collapsed, is the text it had on
20 Oct, with only the additions the matchmaker makes on purpose (Tasks 7
and 11 add theirs to EXPECTED_ADDITIONS).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from database import api_tx
from service.man_woman import opposite_gender_sql

pytestmark = pytest.mark.usefixtures('matchmaker_schema')

SNAPSHOT = (Path(__file__).resolve().parent / 'fixtures' / 'deck_query_2026-10-20.txt').read_text(
    encoding='utf-8').strip()


def _squash(sql: str) -> str:
    return re.sub(r'\s+', ' ', sql).strip()


# What the matchmaker adds to the deck on purpose, each exactly once, as
# squashed text. Task 7: "See who joined" sorts the new fits first.
EXPECTED_ADDITIONS = [
    '-- new_fit_ids (TEC-1845, matchmaker 1.13): "See who joined" puts the -- members the latest '
    'alert notice counted first. Empty on every other -- search, so the order is otherwise unchanged. ',
    '(p.id = ANY(%(new_fit_ids)s::INT[])) DESC, ',
    # Task 11: the searcher who prefers not to be matched with members who
    # share conversations with a mentor.
    '-- Matchmaker (TEC-1845, 6.10): a searcher who chose "Do not match me -- with members who share '
    'conversations with a mentor" does not see -- members with a live shared conversation. AND NOT ( '
    'COALESCE((SELECT sp_mm.no_mentor_shared_matches FROM person sp_mm WHERE sp_mm.id = '
    '%(searcher_person_id)s), FALSE) AND EXISTS (SELECT 1 FROM shared_conversation sc WHERE '
    'sc.single_person_id = p.id AND sc.revoked_at IS NULL) ) ',
    # 26 Oct (TEC-1845): men see women and women see men, as on the map.
    _squash('-- Men see women and women see men, as on the map (TEC-1845, 26 Oct).\n'
            'AND ' + opposite_gender_sql('p')) + ' ',
]


def test_the_deck_query_means_what_it_meant():
    """The fragments replace the clauses word for word: the query's text
    with whitespace collapsed is the text it had on 20 Oct, plus exactly the
    matchmaker's additions."""
    from service.search.sql import Q_UNCACHED_SEARCH_2
    text = _squash(Q_UNCACHED_SEARCH_2)
    for added in EXPECTED_ADDITIONS:
        assert text.count(added) == 1, added
        text = text.replace(added, '')
    assert text == SNAPSHOT


def test_the_deck_and_the_alert_read_torah_level_the_same_way():
    from service.search import predicates as pr
    from service.search.sql import Q_UNCACHED_SEARCH_2
    assert _squash(pr.torah_level_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)
    assert _squash(pr.calendar_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)
    assert _squash(pr.gender_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)
    assert _squash(pr.age_bounds_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)


def _passes(fragment: str, person_id: int, **params) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute(f'SELECT 1 FROM person p WHERE p.id = %(pid)s AND {fragment}',
                          dict(params, pid=person_id)).fetchone() is not None


def test_an_unset_field_is_not_a_mismatch(make_person):
    from service.search import predicates as pr
    unset = make_person(name='NoShabbat')
    answered = make_person(name='Sunday')
    with api_tx() as tx:
        tx.execute("""UPDATE person SET ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                      || '{"shabbat": "other", "relocation": "local-only", "wantsChildren": "no"}'::jsonb
                      WHERE id = %(i)s""", dict(i=answered['id']))
    assert _passes(pr.shabbat_sql('p'), unset['id'], shabbats=['saturday-only'])
    assert not _passes(pr.shabbat_sql('p'), answered['id'], shabbats=['saturday-only'])
    assert _passes(pr.relocation_sql('p'), unset['id'], relocations=['will-relocate'])
    assert not _passes(pr.relocation_sql('p'), answered['id'], relocations=['will-relocate'])
    assert _passes(pr.wants_children_sql('p'), unset['id'], wants_children='yes')
    assert not _passes(pr.wants_children_sql('p'), answered['id'], wants_children='yes')
    assert _passes(pr.wants_children_sql('p'), answered['id'], wants_children=None)
    assert _passes(pr.countries_sql('p'), unset['id'], countries=['US'])
    assert _passes(pr.shabbat_sql('p'), answered['id'], shabbats=[])


def test_countries_match_by_code(make_person):
    from service.search import predicates as pr
    p = make_person(name='Jamaica')
    with api_tx() as tx:
        tx.execute("UPDATE person SET country = 'JM' WHERE id = %(i)s", dict(i=p['id']))
    assert _passes(pr.countries_sql('p'), p['id'], countries=['JM', 'BB'])
    assert not _passes(pr.countries_sql('p'), p['id'], countries=['GB'])
    assert _passes(pr.countries_sql('p'), p['id'], countries=[])


def test_the_base_leaves_out_who_the_deck_leaves_out(make_person, add_photo):
    from service.search import predicates as pr
    owner = make_person(name='BaseOwner', gender='Man')

    def member(name):
        p = make_person(name=name, gender='Woman')
        with api_tx() as tx:
            tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=p['id']))
        add_photo(p['id'])
        return p

    plain = member('Plain')
    hidden = member('Hidden')
    held = member('Held')
    staff = member('Staff')
    blocked = member('Blocked')
    unmatched = member('Unmatched')
    inactive = member('Inactive')
    no_photo = make_person(name='NoPhoto', gender='Woman')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=no_photo['id']))
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s', dict(i=hidden['id']))
        tx.execute('UPDATE person SET verification_required = TRUE WHERE id = %(i)s', dict(i=held['id']))
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=inactive['id']))
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                   'VALUES (%(a)s, %(b)s, TRUE)', dict(a=blocked['id'], b=owner['id']))
        tx.execute('INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by) '
                   'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int), %(a)s)',
                   dict(a=unmatched['id'], b=owner['id']))
    base = pr.deck_base_sql('p', '%(owner)s')
    assert _passes(base, plain['id'], owner=owner['id'])
    for p in (hidden, held, staff, blocked, unmatched, inactive, no_photo):
        assert not _passes(base, p['id'], owner=owner['id']), p
    assert not _passes(base, owner['id'], owner=owner['id'])
    # A visitor has no pairs: only the account checks apply.
    visitor = pr.deck_base_sql('p', None)
    assert _passes(visitor, blocked['id']) and _passes(visitor, unmatched['id'])
    assert not _passes(visitor, hidden['id']) and not _passes(visitor, staff['id'])
