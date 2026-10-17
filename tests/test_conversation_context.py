"""The shared question in a new match (TEC-1845, spec "What members get" 5).

Both members get the same question, chosen once: one neither has answered
if there is one. Each answers first, then sees the other's. No context
without a match, or once the other member is deactivated. Nothing is
written into the chat server.
"""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema', 'questions_live')


@pytest.fixture
def pair(make_person, sign_in):
    a, b = make_person(name='CtxA', gender='Man'), make_person(name='CtxB', gender='Woman')
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        match_id = str(tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id)
                                     VALUES (%(a)s, %(b)s) RETURNING match_id""",
                                  dict(a=lo, b=hi)).fetchone()['match_id'])
    return dict(a=dict(a, headers=sign_in(a)), b=dict(b, headers=sign_in(b)), match_id=match_id)


def _ctx(client, me, other):
    return client.get(f"/conversation-context/{other['uuid']}", headers=me['headers'])


def test_both_members_get_the_same_question(client, pair):
    ra, rb = _ctx(client, pair['a'], pair['b']), _ctx(client, pair['b'], pair['a'])
    assert ra.status_code == rb.status_code == 200, ra.get_data(as_text=True)
    assert ra.get_json()['match_question']['question'] == rb.get_json()['match_question']['question']
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM match_question WHERE match_id = %(m)s::uuid',
                       dict(m=pair['match_id'])).fetchone()['n']
    assert n == 1


def test_the_question_is_one_neither_member_has_answered(client, pair, make_question):
    answered = make_question(sort=-100)
    fresh = make_question(sort=-99)
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)""",
                   dict(p=pair['a']['id'], k=answered['key'], c=answered['options'][0]['key']))
    assert _ctx(client, pair['a'], pair['b']).get_json()['match_question']['question']['key'] == fresh['key']


def test_theirs_stays_hidden_until_you_answer(client, pair):
    q = _ctx(client, pair['a'], pair['b']).get_json()['match_question']['question']
    first, second = (o['key'] for o in q['options'][:2])
    client.put(f"/answers/{q['key']}", headers=pair['b']['headers'], json=dict(choice_key=first))
    mq = _ctx(client, pair['a'], pair['b']).get_json()['match_question']
    assert (mq['mine'], mq['they_answered'], mq['theirs']) == (None, True, None)
    client.put(f"/answers/{q['key']}", headers=pair['a']['headers'], json=dict(choice_key=second))
    mq = _ctx(client, pair['a'], pair['b']).get_json()['match_question']
    assert (mq['mine'], mq['they_answered'], mq['theirs']) == (second, True, first)
    mq = _ctx(client, pair['b'], pair['a']).get_json()['match_question']
    assert (mq['mine'], mq['theirs']) == (first, second)


def test_no_context_without_a_match(client, pair, make_person):
    stranger = make_person(name='CtxStranger')
    assert _ctx(client, pair['a'], stranger).status_code == 404
    assert client.get('/conversation-context/not-a-uuid', headers=pair['a']['headers']).status_code == 404


def test_a_match_with_a_deactivated_member_has_no_context(client, pair):
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=pair['b']['id']))
    assert _ctx(client, pair['a'], pair['b']).status_code == 404


def test_both_members_opening_the_chat_at_once_is_not_a_500(client, pair, make_question):
    """The other member's request assigns the match question first and
    commits while this one is waiting on it. Under REPEATABLE READ the
    INSERT ... ON CONFLICT DO NOTHING then fails to serialise."""
    import threading
    import time

    import psycopg

    import database

    q = make_question(sort=-200)
    other = psycopg.connect(database._api_conninfo)
    other.execute('INSERT INTO match_question (match_id, prompt_key) VALUES (%s::uuid, %s)',
                  (pair['match_id'], q['key']))

    def commit_soon():
        time.sleep(1)
        other.commit()
        other.close()

    t = threading.Thread(target=commit_soon)
    t.start()
    try:
        r = _ctx(client, pair['a'], pair['b'])
    finally:
        t.join()
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['match_question']['question']['key'] == q['key']


def test_a_blocked_pair_gets_nothing(client, pair):
    with api_tx() as tx:
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported)
                      VALUES (%(a)s, %(b)s, TRUE)""", dict(a=pair['a']['id'], b=pair['b']['id']))
    assert _ctx(client, pair['a'], pair['b']).status_code == 404
    assert _ctx(client, pair['b'], pair['a']).status_code == 404, 'a block hides both ways'
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM match_question WHERE match_id = %(m)s::uuid',
                          dict(m=pair['match_id'])).fetchone() is None
