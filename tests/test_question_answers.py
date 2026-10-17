"""Answering a quick question (TEC-1845).

One answer per member per question, changed by answering again. An email
click saves only when nothing is saved yet (keep_existing). A question that
is switched off, unknown or open (release 2) is closed. The split is counts,
shown only from 5 member answers and only to a member who has answered;
staff answers are not counted.
"""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema', 'questions_live')


def _member(make_person, sign_in, name: str) -> dict:
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def _answer(person_id: int, key: str, choice: str) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)""", dict(p=person_id, k=key, c=choice))


def test_an_answer_is_saved_and_can_be_changed(client, make_person, sign_in, make_question):
    q = make_question()
    a, b = (o['key'] for o in q['options'])
    me = _member(make_person, sign_in, 'AnswerMe')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['my_choice'] == a and r.get_json()['counts'] is None
    assert r.get_json()['question'] == q
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=b))
    assert r.get_json()['my_choice'] == b
    mine = client.get('/answers', headers=me['headers']).get_json()['answers']
    assert [x['choice_key'] for x in mine if x['question']['key'] == q['key']] == [b]


def test_keep_existing_never_overwrites(client, make_person, sign_in, make_question):
    q = make_question()
    a, b = (o['key'] for o in q['options'])
    me = _member(make_person, sign_in, 'KeepMe')
    client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=b, keep_existing=True))
    assert r.status_code == 200 and r.get_json()['my_choice'] == a
    other = _member(make_person, sign_in, 'KeepFirst')
    r = client.put(f"/answers/{q['key']}", headers=other['headers'], json=dict(choice_key=b, keep_existing=True))
    assert r.get_json()['my_choice'] == b


def test_a_closed_or_unknown_question_is_refused(client, make_person, sign_in, make_question):
    off = make_question(active=False)
    me = _member(make_person, sign_in, 'ClosedMe')
    for key in (off['key'], 'no-such-question', 'pet'):
        r = client.put(f'/answers/{key}', headers=me['headers'],
                       json=dict(choice_key=off['options'][0]['key']))
        assert r.status_code == 404, key
        assert r.get_json() == dict(error='closed')


def test_a_choice_the_question_does_not_offer_is_refused(client, make_person, sign_in, make_question):
    q = make_question()
    me = _member(make_person, sign_in, 'BadChoice')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key='not-an-option'))
    assert r.status_code == 400 and r.get_json() == dict(error='bad_choice')


def test_the_split_shows_from_5_answers_to_a_member_who_answered(client, make_person, sign_in, make_question):
    q = make_question(labels=('Mountains', 'The sea'))
    a, b = (o['key'] for o in q['options'])
    for i, choice in enumerate((a, a, a)):
        _answer(make_person(name=f'Split{i}')['id'], q['key'], choice)
    fourth = _member(make_person, sign_in, 'SplitFourth')
    r = client.put(f"/answers/{q['key']}", headers=fourth['headers'], json=dict(choice_key=b))
    assert r.get_json()['counts'] is None, '4 answers must not show a split'
    fifth = _member(make_person, sign_in, 'SplitFifth')
    r = client.put(f"/answers/{q['key']}", headers=fifth['headers'], json=dict(choice_key=b))
    assert r.get_json()['counts'] == [dict(key=a, n=3), dict(key=b, n=2)]


def test_staff_answers_are_not_counted(client, make_person, sign_in, make_question):
    q = make_question()
    a, _ = (o['key'] for o in q['options'])
    for i in range(3):
        _answer(make_person(name=f'Counted{i}')['id'], q['key'], a)
    staff = make_person(name='StaffAnswer')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    _answer(staff['id'], q['key'], a)
    me = _member(make_person, sign_in, 'CountedMe')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    assert r.get_json()['counts'] is None, 'the staff answer made it look like 5'


def test_signed_out_is_turned_away(client):
    r = client.put('/answers/mountains-or-sea', json=dict(choice_key='sea'))
    assert r.status_code == 400
