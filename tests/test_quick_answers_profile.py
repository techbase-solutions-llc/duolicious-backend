"""Quick answers on a profile (TEC-1845, spec "Where answers show").

The server enforces "answer to see theirs": a question the viewer has not
answered comes back locked, with no choice anywhere in the response. Shared
answers are marked. Never to signed-out viewers and never on a limited
(hidden) profile. A question switched off leaves every profile.
"""
from __future__ import annotations

import json

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema', 'questions_live')

_COUNTRY = 'XQ'


@pytest.fixture
def world(make_person, add_photo, sign_in):
    """As tests/test_photo_gate.py builds it: a viewer and a woman with an
    approved face photo, in each other's search country."""
    viewer = make_person(name='QaViewer', gender='Man')
    other = make_person(name='QaOther', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = TRUE, country = %(c)s,
                      show_my_location = TRUE, last_online_time = NOW(),
                      ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                     || '{"citySet": true}'::jsonb
                WHERE id = ANY(%(i)s)""",
            dict(c=_COUNTRY, i=[viewer['id'], other['id']]))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) "
                   "VALUES (%(i)s, %(c)s)", dict(i=viewer['id'], c=_COUNTRY))
    add_photo(other['id'], position=1, face_count=1)
    return dict(viewer=viewer, other=other, headers=sign_in(viewer))


def _answer(person_id, question, index):
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)
                      ON CONFLICT (person_id, prompt_key) DO UPDATE SET choice_key = EXCLUDED.choice_key""",
                   dict(p=person_id, k=question['key'], c=question['options'][index]['key']))


def _profile(client, world, headers=True):
    r = client.get(f"/prospect-profile/{world['other']['uuid']}",
                   headers=world['headers'] if headers else None)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def _by_key(r) -> dict:
    return {x['question']['key']: x for x in r.get_json()['quick_answers']}


def test_a_question_the_viewer_has_not_answered_comes_back_locked(client, world, make_question):
    shared, locked = make_question(), make_question()
    _answer(world['other']['id'], shared, 0)
    _answer(world['other']['id'], locked, 1)
    _answer(world['viewer']['id'], shared, 0)
    r = _profile(client, world)
    got = _by_key(r)
    assert got[shared['key']] == dict(question=shared, locked=False,
                                      choice_key=shared['options'][0]['key'], shared=True)
    assert got[locked['key']] == dict(question=locked, locked=True, choice_key=None, shared=False)
    # The question lists every option key, as it should. Anywhere else in
    # the response, their locked choice is a leak.
    j = r.get_json()
    elsewhere = dict(j, quick_answers=[dict(x, question=None) for x in j['quick_answers']])
    assert locked['options'][1]['key'] not in json.dumps(elsewhere), 'their locked answer leaked'


def test_a_different_answer_is_shown_but_not_shared(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    _answer(world['viewer']['id'], q, 1)
    got = _by_key(_profile(client, world))[q['key']]
    assert (got['locked'], got['choice_key'], got['shared']) == (False, q['options'][0]['key'], False)


def test_signed_out_viewers_get_no_quick_answers(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    # A signed-out visitor sees only a profile opted in to public_profile.
    with api_tx() as tx:
        tx.execute('UPDATE person SET public_profile = TRUE WHERE id = %(i)s', dict(i=world['other']['id']))
    assert 'quick_answers' not in _profile(client, world, headers=False).get_json()


def test_a_hidden_members_short_profile_carries_none(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    with api_tx() as tx:
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s', dict(i=world['other']['id']))
    j = _profile(client, world).get_json()
    assert j['limited'] is True and 'quick_answers' not in j


def test_an_answer_to_a_question_switched_off_is_not_shown(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    with api_tx() as tx:
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE key = %(k)s', dict(k=q['key']))
    assert q['key'] not in _by_key(_profile(client, world))
