"""Migration 0079: the profile views already recorded between two members
who are not one man and one woman, or recorded by staff, are archived and
then removed (TEC-1845, 26 Oct 2026).

Every removed row is copied unchanged into its archive table first, the
rows that stay are untouched, and a second run changes nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from database import api_tx

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0079_views_man_woman_only.sql')


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture
def people(make_person):
    p = dict(
        man=make_person(name='M79Man', gender='Man'),
        man2=make_person(name='M79Man2', gender='Man'),
        woman=make_person(name='M79Woman', gender='Woman'),
        woman2=make_person(name='M79Woman2', gender='Woman'),
        other=make_person(name='M79Other', gender='Other'),
        staff=make_person(name='M79Staff', gender='Man'),
    )
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['staff']['id']))
    return p


# (viewer, viewed, stays, reason when removed)
PAIRS = [
    ('man', 'woman', True, None),
    ('woman', 'man', True, None),
    ('woman', 'staff', True, None),       # the viewed being staff is no reason
    ('man', 'man2', False, 'not_man_woman'),
    ('woman', 'woman2', False, 'not_man_woman'),
    ('other', 'woman', False, 'not_man_woman'),
    ('man', 'other', False, 'not_man_woman'),
    ('staff', 'woman', False, 'staff'),
    ('staff', 'man', False, 'staff'),
]


def _seed(people):
    with api_tx() as tx:
        for i, (a, b, _, _) in enumerate(PAIRS):
            tx.execute(
                """INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
                   VALUES (%(a)s, %(b)s, '2026-10-01 12:00'::timestamp + %(i)s * INTERVAL '1 minute',
                           %(inv)s)""",
                dict(a=people[a]['id'], b=people[b]['id'], i=i, inv=i % 2 == 0))
            tx.execute(
                """INSERT INTO profile_view (viewer_id, viewed_id, last_notified_at)
                   VALUES (%(a)s, %(b)s, '2026-10-02 12:00+00'::timestamptz + %(i)s * INTERVAL '1 minute')""",
                dict(a=people[a]['id'], b=people[b]['id'], i=i))


def _state(people):
    ids = [p['id'] for p in people.values()]
    with api_tx() as tx:
        q = lambda sql: [tuple(r.values()) for r in tx.execute(sql, dict(i=ids)).fetchall()]
        return dict(
            visited=q("""SELECT subject_person_id, object_person_id, updated_at, invisible
                           FROM visited WHERE subject_person_id = ANY(%(i)s)
                          ORDER BY 1, 2"""),
            profile_view=q("""SELECT viewer_id, viewed_id, last_notified_at
                                FROM profile_view WHERE viewer_id = ANY(%(i)s) ORDER BY 1, 2"""),
            visited_removed=q("""SELECT subject_person_id, object_person_id, updated_at, invisible,
                                        reason
                                   FROM visited_removed_20261026
                                  WHERE subject_person_id = ANY(%(i)s) ORDER BY 1, 2"""),
            profile_view_removed=q("""SELECT viewer_id, viewed_id, last_notified_at, reason
                                        FROM profile_view_removed_20261026
                                       WHERE viewer_id = ANY(%(i)s) ORDER BY 1, 2"""),
        )


def test_archives_then_removes_exactly_the_wrong_views_and_a_rerun_changes_nothing(people):
    _apply()  # the archive tables exist before the rows are seeded
    _seed(people)
    with api_tx() as tx:
        before_v = {(r['subject_person_id'], r['object_person_id']): r for r in tx.execute(
            'SELECT * FROM visited WHERE subject_person_id = ANY(%(i)s)',
            dict(i=[p['id'] for p in people.values()])).fetchall()}
        before_pv = {(r['viewer_id'], r['viewed_id']): r for r in tx.execute(
            'SELECT * FROM profile_view WHERE viewer_id = ANY(%(i)s)',
            dict(i=[p['id'] for p in people.values()])).fetchall()}

    _apply()
    after = _state(people)

    key = lambda a, b: (people[a]['id'], people[b]['id'])
    kept = sorted(key(a, b) for a, b, stays, _ in PAIRS if stays)
    gone = {key(a, b): reason for a, b, stays, reason in PAIRS if not stays}

    assert sorted(r[:2] for r in after['visited']) == kept
    assert sorted(r[:2] for r in after['profile_view']) == kept

    # Archived unchanged, each with its reason.
    assert {r[:2]: r for r in after['visited_removed']} == {
        k: (*k, before_v[k]['updated_at'], before_v[k]['invisible'], reason)
        for k, reason in gone.items()}
    assert {r[:2]: r for r in after['profile_view_removed']} == {
        k: (*k, before_pv[k]['last_notified_at'], reason) for k, reason in gone.items()}

    _apply()
    assert _state(people) == after
