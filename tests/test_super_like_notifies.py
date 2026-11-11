"""A super like tells the member as a like does (TEC-2065, 11 Nov 2026).

POST /tokens/super-like wrote the like and, when it was mutual, the match,
but sent nothing: no "someone likes you" and no "it's a match". It now
sends exactly what a like through /decisions sends, through the same
notify() (so the same switches, preferences, quiet hours and dedupe): a
like notice on a new like, a match notice to the other person on a new
match, and nothing for a re-tap.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service.tokens import credit


@pytest.fixture
def pair(make_person, sign_in):
    adam = make_person(name='SlnAdam', gender='Man')
    chava = make_person(name='SlnChava', gender='Woman')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[adam['id'], chava['id']]))
        credit(tx, adam['uuid'], 10, reason='purchase', metadata={})
    return adam, chava, sign_in(adam)


@pytest.fixture
def calls(monkeypatch):
    import service.notifications as notifications
    sent = []
    monkeypatch.setattr(notifications, 'notify',
                        lambda person_id, kind, **kw: sent.append((person_id, kind, kw)))
    return sent


def _super_like(client, h, whom):
    r = client.post('/tokens/super-like', json={'person_id': whom['uuid']}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_a_super_like_sends_the_like_notice(client, pair, calls):
    adam, chava, h = pair
    _super_like(client, h, chava)
    assert [(c[0], c[1]) for c in calls] == [(chava['id'], 'like')]
    kw = calls[0][2]
    assert kw['url'] == '/matches?tab=likes'
    assert kw['title'] == 'Someone likes you'
    assert kw['email_event_id'] == f"like-{adam['id']}"


def test_a_super_like_that_matches_sends_the_match_notice(client, pair, calls):
    adam, chava, h = pair
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(c)s, %(a)s)',
                   dict(a=adam['id'], c=chava['id']))
    body = _super_like(client, h, chava)
    assert body['match_id']
    assert [(c[0], c[1]) for c in calls] == [(chava['id'], 'match')]
    kw = calls[0][2]
    assert kw['body'] == 'SlnAdam likes you back'
    assert kw['tag'] == f"match:{body['match_id']}"
    assert kw['email_event_id'] == f"match-{body['match_id']}"


def test_a_re_tap_sends_nothing_more(client, pair, calls):
    _adam, chava, h = pair
    _super_like(client, h, chava)
    _super_like(client, h, chava)
    assert len(calls) == 1


def test_a_super_like_over_an_earlier_like_sends_no_second_like_notice(client, pair, calls):
    adam, chava, h = pair
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(c)s)',
                   dict(a=adam['id'], c=chava['id']))
    _super_like(client, h, chava)
    assert calls == []
