"""The checklist v2's answers and comparison (TEC-1845).

Spec: "'Where you agree', item by item, with the importance each person
gave it. 'Talk about these', for differing stances or importance two or
more points apart. Each person's own items side by side." Exodus 21:10-11
stays as today, the husband's passage only (owner decision 9).
"""
from __future__ import annotations

import pytest

from service.tools import checklist


def _p(importance, stance='agree', **kw):
    return dict(section='biblical', importance=importance, stance=stance, **kw)


def _own(title, importance, section='nice-to-have', **kw):
    return dict(section=section, title=title, importance=importance, **kw)


def test_the_passages_are_todays_nine_with_exodus_for_the_husband_only():
    assert list(checklist.PASSAGES) == [f'p{i}' for i in range(1, 10)]
    assert checklist.PASSAGES['p2'] == ('Exodus 21:10-11', ('husband',))


@pytest.mark.parametrize('key,answer,role,reason', [
    ('p2', _p(4), 'wife', 'bad_question'),
    ('p1', _p(4), None, 'role_required'),
    ('p10', _p(4), 'wife', 'bad_question'),
    ('p1', _p(6), 'wife', 'bad_answer'),
    ('p1', dict(section='nice-to-have', importance=3), 'wife', 'bad_answer'),
    ('own-garden1', dict(section='nice-to-have', importance=3), 'wife', 'bad_answer'),
    ('own-garden1', _own('A garden', 3, section='biblical'), 'wife', 'bad_answer'),
    ('own-x', _own('A garden', 3), 'wife', 'bad_question'),
])
def test_a_bad_checklist_answer_is_refused(key, answer, role, reason):
    with pytest.raises(ValueError, match=reason):
        checklist.clean_checklist_answer(key, answer, role)


def test_a_clean_answer_keeps_what_the_email_needs_and_drops_blanks():
    clean = checklist.clean_checklist_answer(
        'own-garden1', _own('  A garden we grow together ', 4, comment='', examples=['', ' tomatoes ']),
        'husband')
    assert clean == dict(section='nice-to-have', title='A garden we grow together', importance=4,
                         examples=['tomatoes'])


def test_the_comparison_tags_what_to_talk_about():
    owner = {'p1': _p(4), 'p3': _p(5), 'p4': _p(3), 'p5': _p(2), 'p2': _p(5),
             'own-garden1': _own('A garden we grow together', 4)}
    guest = {'p1': _p(5), 'p3': _p(5, 'other', other_note='Near my parents'), 'p4': _p(5),
             'p5': _p(2), 'own-host1': _own('Hosting the feasts at home', 5),
             'own-hours1': _own('My work hours', 3, section='challenge', stance='agree')}
    c = checklist.compare(owner, guest)
    assert (c['agree'], c['total']) == (2, 4)
    assert [i['key'] for i in c['agree_items']] == ['p1', 'p5']
    assert [(i['key'], i['tag']) for i in c['talk_items']] == [('p3', 'stance'), ('p4', 'importance')]
    assert c['talk_items'][0]['guest']['other_note'] == 'Near my parents'
    assert [i['title'] for i in c['own']['owner']] == ['A garden we grow together']
    assert [i['title'] for i in c['own']['guest']] == ['Hosting the feasts at home', 'My work hours']


def test_nothing_to_talk_about_and_no_own_items():
    c = checklist.compare({'p1': _p(4)}, {'p1': _p(5)})
    assert (c['agree'], c['total'], c['talk_items'], c['own']) == (
        1, 1, [], {'owner': [], 'guest': []})


def test_the_top_items_leave_challenges_out():
    answers = {'p1': _p(3), 'p3': _p(5), 'own-pray1': _own('We pray together every evening', 5),
               'own-hours1': _own('My work hours', 5, section='challenge', stance='agree'),
               'p9': _p(4)}
    top = checklist.top_items(answers)
    assert [t['key'] for t in top] == ['p3', 'own-pray1', 'p9']
    assert top[0]['ref'] == 'Proverbs 5:15-19' and top[1]['title'] == 'We pray together every evening'


def test_the_summary_answers_carry_each_passage_reference():
    out = checklist.to_summary_answers({'p2': _p(5, comment='Provide'), 'own-pray1': _own('Pray', 4)})
    assert out[0]['ref'] == 'Exodus 21:10-11' and out[0]['comment'] == 'Provide'
    assert out[1]['title'] == 'Pray' and 'ref' not in out[1]
