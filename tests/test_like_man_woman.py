"""A like, a super like, a match and a message are between a man and a woman
only (TEC-2038, 11 Nov 2026).

Q_RECORD_LIKE and the super like never checked gender, so a member holding a
link to a same-gender profile could like or super like it, and two such
likes made a match. Now neither writes anything across a same-gender pair,
no match is made, a message is refused and a same-gender profile reads as
not found. A viewer who is neither a man nor a woman pairs with nobody.
Staff still open every profile (TEC-2040: staff still see everyone).
"""
from __future__ import annotations

import pytest

from database import api_tx
from service.tokens import credit, get_balance


@pytest.fixture
def folk(make_person, sign_in):
    people = dict(
        adam=make_person(name='MwAdam', gender='Man'),
        boaz=make_person(name='MwBoaz', gender='Man'),
        chava=make_person(name='MwChava', gender='Woman'),
        dinah=make_person(name='MwDinah', gender='Woman'),
        other=make_person(name='MwOther', gender='Other'),
    )
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[p['id'] for p in people.values()]))
    people['h'] = {k: sign_in(v) for k, v in people.items()}
    return people


def _liked(a, b) -> bool:
    with api_tx() as tx:
        return tx.execute('SELECT 1 FROM liked WHERE liker_id = %(a)s AND liked_id = %(b)s',
                          dict(a=a['id'], b=b['id'])).fetchone() is not None


def _matched(a, b) -> bool:
    with api_tx() as tx:
        return tx.execute(
            'SELECT 1 FROM ahavah_match WHERE user_a_id = LEAST(%(a)s, %(b)s) '
            'AND user_b_id = GREATEST(%(a)s, %(b)s)',
            dict(a=a['id'], b=b['id'])).fetchone() is not None


def _like(client, folk, who, whom):
    r = client.post('/decisions', json={'profile_uuid': folk[whom]['uuid'], 'decision': 'like'},
                    headers=folk['h'][who])
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


@pytest.mark.parametrize('who,whom', [('adam', 'boaz'), ('chava', 'dinah'),
                                      ('other', 'chava'), ('adam', 'other')])
def test_a_like_outside_a_man_and_a_woman_records_nothing(client, folk, who, whom):
    assert _like(client, folk, who, whom) == {'match': None}
    assert not _liked(folk[who], folk[whom])


def test_two_same_gender_likes_never_match(client, folk):
    # Boaz's like already exists (written before the fix).
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(b)s, %(a)s)',
                   dict(a=folk['adam']['id'], b=folk['boaz']['id']))
    assert _like(client, folk, 'adam', 'boaz') == {'match': None}
    assert not _matched(folk['adam'], folk['boaz'])


def test_a_man_and_a_woman_still_match(client, folk):
    assert _like(client, folk, 'chava', 'adam') == {'match': None}
    assert _like(client, folk, 'adam', 'chava')['match'] is not None
    assert _matched(folk['adam'], folk['chava'])


@pytest.mark.parametrize('who,whom', [('adam', 'boaz'), ('other', 'chava')])
def test_a_super_like_outside_a_man_and_a_woman_is_not_found_and_costs_nothing(
        client, folk, who, whom):
    with api_tx() as tx:
        credit(tx, folk[who]['uuid'], 5, reason='purchase', metadata={})
        # A same-gender like back, so a super like would otherwise match.
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(b)s, %(a)s)',
                   dict(a=folk[who]['id'], b=folk[whom]['id']))
    r = client.post('/tokens/super-like', json={'person_id': folk[whom]['uuid']},
                    headers=folk['h'][who])
    assert r.status_code == 404
    assert r.get_json() == {'error': 'not_available'}
    assert not _liked(folk[who], folk[whom])
    assert not _matched(folk[who], folk[whom])
    with api_tx() as tx:
        assert get_balance(tx, folk[who]['uuid']) == 5


@pytest.mark.parametrize('who,whom', [('adam', 'boaz'), ('dinah', 'chava'), ('other', 'chava')])
def test_a_same_gender_profile_reads_as_not_found(client, folk, who, whom):
    assert client.get(f"/prospect-profile/{folk[whom]['uuid']}",
                      headers=folk['h'][who]).status_code == 404
    assert client.get(f"/conversation-prospect/{folk[whom]['uuid']}",
                      headers=folk['h'][who]).status_code == 404


def test_a_hidden_same_gender_profile_reads_as_not_found(client, folk):
    with api_tx() as tx:
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s',
                   dict(i=folk['boaz']['id']))
    assert client.get(f"/prospect-profile/{folk['boaz']['uuid']}",
                      headers=folk['h']['adam']).status_code == 404


def test_a_man_opens_a_womans_profile_and_staff_open_any(client, folk):
    assert client.get(f"/prospect-profile/{folk['chava']['uuid']}",
                      headers=folk['h']['adam']).status_code == 200
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s",
                   dict(i=folk['adam']['id']))
    assert client.get(f"/prospect-profile/{folk['boaz']['uuid']}",
                      headers=folk['h']['adam']).status_code == 200


def test_a_message_between_two_men_is_refused(folk):
    from service.chat.chatutil import Q_IS_SKIPPED
    with api_tx() as tx:
        same = tx.execute(Q_IS_SKIPPED, dict(from_id=folk['adam']['id'],
                                             to_id=folk['boaz']['id'])).fetchone()
        pair = tx.execute(Q_IS_SKIPPED, dict(from_id=folk['adam']['id'],
                                             to_id=folk['chava']['id'])).fetchone()
    assert same is not None
    assert pair is None


@pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')
def test_an_introduction_between_two_men_never_matches(client, folk):
    with api_tx() as tx:
        iid = tx.execute(
            """INSERT INTO introduction (introducer_person_id, a_person_id, b_person_id, status,
                                         closes_at, opened_at)
               VALUES (%(i)s, %(a)s, %(b)s, 'open', NOW() + INTERVAL '14 days', NOW())
               RETURNING id""",
            dict(i=folk['chava']['id'], a=folk['adam']['id'], b=folk['boaz']['id'])).fetchone()['id']
    for who in ('adam', 'boaz'):
        r = client.post(f'/introductions/{iid}/accept', headers=folk['h'][who])
        assert r.status_code == 410, r.get_data(as_text=True)
    assert not _matched(folk['adam'], folk['boaz'])
    assert not _liked(folk['adam'], folk['boaz'])
