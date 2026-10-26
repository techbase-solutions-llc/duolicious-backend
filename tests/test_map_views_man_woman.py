"""Men are shown women and women are shown men, never otherwise (TEC-1845,
owner's report of 26 Oct 2026).

The map filtered on the viewer's saved gender preference and, when there
was none, showed everyone, so a man saw men. Opening a profile wrote a
`visited` row and could send a "someone viewed your profile" push whatever
the two members' genders, and staff browsing members counted as visitors.

Now the map only ever shows the gender opposite the viewer's own, and a
view counts (a `visited` row, a `profile_view` row, a push) only from a man
to a woman or a woman to a man, and never from a staff account. The profile
still opens for every viewer it opened for before.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service import notifications


def _on_the_map(*people):
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = TRUE, show_my_location = TRUE,
                      last_online_time = NOW(),
                      ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                     || '{"citySet": true}'::jsonb
                WHERE id = ANY(%(i)s)""",
            dict(i=[p['id'] for p in people]))


def _prefer(person, *genders):
    with api_tx() as tx:
        tx.execute('DELETE FROM search_preference_gender WHERE person_id = %(i)s',
                   dict(i=person['id']))
        for g in genders:
            tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                       "SELECT %(i)s, id FROM gender WHERE name = %(g)s",
                       dict(i=person['id'], g=g))


@pytest.fixture
def town(make_person, add_photo, sign_in):
    """Two men and two women, all on the map with an approved photo."""
    people = dict(
        adam=make_person(name='MapAdam', gender='Man'),
        boaz=make_person(name='MapBoaz', gender='Man'),
        chava=make_person(name='MapChava', gender='Woman'),
        dinah=make_person(name='MapDinah', gender='Woman'),
    )
    _on_the_map(*people.values())
    for p in people.values():
        add_photo(p['id'])
    people['sign_in'] = sign_in
    return people


def _marker_uuids(client, headers):
    r = client.get('/map/markers', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {m['uuid'] for m in r.get_json()['markers']}


def _gender_names(uuids):
    with api_tx() as tx:
        return {r['name'] for r in tx.execute(
            """SELECT DISTINCT g.name FROM person p JOIN gender g ON g.id = p.gender_id
                WHERE p.uuid::text = ANY(%(u)s)""", dict(u=list(uuids))).fetchall()}


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def test_a_man_sees_only_women_on_the_map(client, town):
    _prefer(town['adam'], 'Woman')
    seen = _marker_uuids(client, town['sign_in'](town['adam']))
    assert {town['chava']['uuid'], town['dinah']['uuid']} <= seen
    assert town['boaz']['uuid'] not in seen
    assert _gender_names(seen) <= {'Woman'}


def test_a_woman_sees_only_men_on_the_map(client, town):
    _prefer(town['chava'], 'Man')
    seen = _marker_uuids(client, town['sign_in'](town['chava']))
    assert {town['adam']['uuid'], town['boaz']['uuid']} <= seen
    assert town['dinah']['uuid'] not in seen
    assert _gender_names(seen) <= {'Man'}


@pytest.mark.parametrize('viewer,other_gender', [('adam', 'Woman'), ('chava', 'Man')])
def test_no_saved_preference_still_shows_only_the_opposite_gender(client, town, viewer,
                                                                    other_gender):
    _prefer(town[viewer])
    seen = _marker_uuids(client, town['sign_in'](town[viewer]))
    assert seen, 'the opposite gender is still on the map'
    assert _gender_names(seen) == {other_gender}


def test_a_same_gender_preference_shows_nobody_of_the_same_gender(client, town):
    _prefer(town['adam'], 'Man')
    seen = _marker_uuids(client, town['sign_in'](town['adam']))
    assert town['boaz']['uuid'] not in seen
    assert 'Man' not in _gender_names(seen)


def test_a_viewer_who_is_neither_man_nor_woman_sees_no_markers(client, town, make_person):
    other = make_person(name='MapOther', gender='Other')
    _on_the_map(other)
    assert _marker_uuids(client, town['sign_in'](other)) == set()


# ---------------------------------------------------------------------------
# Profile views
# ---------------------------------------------------------------------------

_DEFERRED: list = []


@pytest.fixture
def pushes(monkeypatch):
    """Hold the profile-view recorder's thread until the request has
    returned (the limited path calls it inside its own transaction, and the
    test pool would starve if it ran inline), then run it on this thread.
    Captures the pushes it would send."""
    sent: list[dict] = []
    _DEFERRED.clear()

    class _Deferred:
        def __init__(self, target, kwargs=None, **_):
            self._target, self._kwargs = target, kwargs or {}

        def start(self):
            _DEFERRED.append(self)

    monkeypatch.setattr(notifications.threading, 'Thread', _Deferred)
    monkeypatch.setattr(notifications, 'send_to_user_safe', lambda **kw: sent.append(kw))
    return sent


def _run_deferred():
    while _DEFERRED:
        t = _DEFERRED.pop(0)
        t._target(**t._kwargs)


def _wants_view_pushes(person):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO notification_preference (person_id, push_profile_views)
               VALUES (%(i)s, TRUE)
               ON CONFLICT (person_id) DO UPDATE SET push_profile_views = TRUE""",
            dict(i=person['id']))


def _make_staff(person, role='admin'):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY[%(r)s]::TEXT[] WHERE id = %(i)s",
                   dict(i=person['id'], r=role))


def _view_rows(viewer, viewed):
    with api_tx() as tx:
        v = tx.execute('SELECT 1 FROM visited WHERE subject_person_id = %(a)s '
                       'AND object_person_id = %(b)s',
                       dict(a=viewer['id'], b=viewed['id'])).fetchone()
        pv = tx.execute('SELECT 1 FROM profile_view WHERE viewer_id = %(a)s '
                        'AND viewed_id = %(b)s',
                        dict(a=viewer['id'], b=viewed['id'])).fetchone()
    return v is not None, pv is not None


def _open(client, town, viewer, viewed):
    r = client.get(f"/prospect-profile/{viewed['uuid']}",
                   headers=town['sign_in'](viewer))
    assert r.status_code == 200, r.get_data(as_text=True)
    _run_deferred()
    return r.get_json()


def _hidden(person):
    with api_tx() as tx:
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s',
                   dict(i=person['id']))


@pytest.mark.parametrize('viewer,viewed', [('adam', 'chava'), ('chava', 'adam')])
def test_a_view_between_a_man_and_a_woman_counts(client, town, pushes, viewer, viewed):
    _wants_view_pushes(town[viewed])
    _open(client, town, town[viewer], town[viewed])
    assert _view_rows(town[viewer], town[viewed]) == (True, True)
    assert [p['person_id'] for p in pushes] == [town[viewed]['id']]


@pytest.mark.parametrize('viewer,viewed', [('adam', 'boaz'), ('chava', 'dinah')])
def test_a_same_gender_view_records_nothing(client, town, pushes, viewer, viewed):
    _wants_view_pushes(town[viewed])
    _open(client, town, town[viewer], town[viewed])
    assert _view_rows(town[viewer], town[viewed]) == (False, False)
    assert pushes == []


@pytest.mark.parametrize('role', ['admin', 'mod'])
@pytest.mark.parametrize('viewed', ['chava', 'boaz'])
def test_a_staff_view_records_nothing(client, town, pushes, viewed, role):
    # The owner, 26 Oct 2026: moderators' views are hidden like admins'.
    _make_staff(town['adam'], role)
    _wants_view_pushes(town[viewed])
    _open(client, town, town['adam'], town[viewed])
    assert _view_rows(town['adam'], town[viewed]) == (False, False)
    assert pushes == []


def test_a_staff_view_of_a_limited_profile_records_nothing(client, town, pushes):
    _make_staff(town['adam'])
    _hidden(town['chava'])
    _wants_view_pushes(town['chava'])
    body = _open(client, town, town['adam'], town['chava'])
    assert body.get('limited') is True
    assert _view_rows(town['adam'], town['chava']) == (False, False)
    assert pushes == []


def test_a_same_gender_view_of_a_limited_profile_records_nothing(client, town, pushes):
    _hidden(town['boaz'])
    _wants_view_pushes(town['boaz'])
    body = _open(client, town, town['adam'], town['boaz'])
    assert body.get('limited') is True
    assert _view_rows(town['adam'], town['boaz']) == (False, False)
    assert pushes == []


def test_a_man_woman_view_of_a_limited_profile_still_counts(client, town, pushes):
    _hidden(town['chava'])
    _wants_view_pushes(town['chava'])
    body = _open(client, town, town['adam'], town['chava'])
    assert body.get('limited') is True
    assert _view_rows(town['adam'], town['chava']) == (True, True)
    assert [p['person_id'] for p in pushes] == [town['chava']['id']]


# ---------------------------------------------------------------------------
# Discover's deck: the same rule as the map
# ---------------------------------------------------------------------------

def _deck(viewer, preference):
    from service.search.sql import Q_CACHED_SEARCH, Q_UNCACHED_SEARCH_1, Q_UNCACHED_SEARCH_2
    from tests.test_deck_gates import DECK_PARAMS
    p = dict(DECK_PARAMS, n=1000, searcher_person_id=viewer['id'],
             gender_preference=preference)
    with api_tx() as tx:
        tx.execute(Q_UNCACHED_SEARCH_1, p)
        tx.execute(Q_UNCACHED_SEARCH_2, p)
        return {r['prospect_uuid'] for r in tx.execute(Q_CACHED_SEARCH, p).fetchall()}


@pytest.mark.parametrize('viewer,same,other', [('adam', 'boaz', 'chava'),
                                               ('chava', 'dinah', 'adam')])
def test_the_deck_with_no_preference_shows_only_the_opposite_gender(town, viewer, same, other):
    seen = _deck(town[viewer], [])
    assert town[other]['uuid'] in seen
    assert town[same]['uuid'] not in seen


def test_the_deck_with_a_same_gender_preference_shows_nobody_of_the_same_gender(town):
    with api_tx() as tx:
        man = tx.execute("SELECT id FROM gender WHERE name = 'Man'").fetchone()['id']
    assert town['boaz']['uuid'] not in _deck(town['adam'], [man])
