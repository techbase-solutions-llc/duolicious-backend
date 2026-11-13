"""A pass from Liked you sticks.

The web posts a plain "nope" from Liked you, and Q_LIST_INCOMING_LIKES
kept plain passes on purpose (migration 0035: a pass must not erase a
like). So the card came back on reload and stayed in the likes count and
the Matches badge (both read /likes/incoming's count). Since 11 Nov 2026 a
pass answers the like. Since 13 Nov 2026 (TEC-2085, decision 10) a pass
removes that person from Liked you for good, as in the deck, whenever it
was made; undoing the pass brings them back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx


@pytest.fixture
def pair(make_person, sign_in):
    me = make_person(name='LyMe', gender='Woman')
    liker = make_person(name='LyLiker', gender='Man')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[me['id'], liker['id']]))
        tx.execute("UPDATE person SET entitlements = ARRAY['premium'] WHERE id = %(i)s",
                   dict(i=me['id']))
    return me, liker, sign_in(me)


def _like(liker, me, at):
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(a)s, %(b)s, %(t)s)',
                   dict(a=liker['id'], b=me['id'], t=at))


def _unlike(liker, me):
    with api_tx() as tx:
        tx.execute('DELETE FROM liked WHERE liker_id = %(a)s AND liked_id = %(b)s',
                   dict(a=liker['id'], b=me['id']))


def _incoming(client, h):
    r = client.get('/likes/incoming', headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    return j['count'], {l['with_profile']['id'] for l in j['likes']}


def _pass(client, h, whom):
    r = client.post('/decisions', json={'profile_uuid': whom['uuid'], 'decision': 'nope'}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)


def test_a_pass_after_the_like_hides_it_from_liked_you(client, pair):
    me, liker, h = pair
    _like(liker, me, datetime.now(timezone.utc) - timedelta(minutes=5))
    assert _incoming(client, h) == (1, {liker['uuid']})
    _pass(client, h, liker)
    assert _incoming(client, h) == (0, set())


def test_a_pass_before_the_like_hides_it_too(client, pair):
    me, liker, h = pair
    _pass(client, h, liker)
    _like(liker, me, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert _incoming(client, h) == (0, set())


def test_a_like_given_again_after_the_pass_stays_hidden(client, pair):
    me, liker, h = pair
    _like(liker, me, datetime.now(timezone.utc) - timedelta(minutes=5))
    _pass(client, h, liker)
    _unlike(liker, me)
    _like(liker, me, datetime.now(timezone.utc) + timedelta(minutes=1))
    assert _incoming(client, h) == (0, set())


def test_undoing_the_pass_brings_the_like_back(client, pair):
    me, liker, h = pair
    _like(liker, me, datetime.now(timezone.utc) - timedelta(minutes=5))
    _pass(client, h, liker)
    r = client.post(f"/unskip/by-uuid/{liker['uuid']}", json={}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _incoming(client, h) == (1, {liker['uuid']})


@pytest.mark.parametrize('module,name,me,liker', [
    ('emails.likes_waiting_weekly', '_Q_DUE', 'l.liked_id', 'l.liker_id'),
    ('emails.send_likes_waiting', '_Q_TARGETS', 'p.id', 'l.liker_id'),
    ('emails.send_community_weekly', '_Q_PERSONAL', 'p.id', 'l.liker_id'),
])
def test_the_likes_waiting_emails_leave_out_an_answered_like(module, name, me, liker):
    """The emails that count likes waiting read the same rule."""
    import importlib
    import re
    from service.decisions.answered import passed_on_liker_sql
    mod = importlib.import_module(module)
    texts = [getattr(mod, name)] if name else [v for v in vars(mod).values() if isinstance(v, str)]
    squash = lambda t: re.sub(r'\s+', ' ', t)
    assert any(squash(passed_on_liker_sql(me, liker)) in squash(t) for t in texts)


def test_a_like_from_someone_passed_on_is_not_announced(make_person, monkeypatch):
    """The card stays hidden, so no "Someone likes you" points at it."""
    import service.notifications as notifications
    from service.decisions import notify_new_like
    me = make_person(name='LyQuiet', gender='Woman')
    liker = make_person(name='LyQuietLiker', gender='Man')
    calls = []
    monkeypatch.setattr(notifications, 'notify', lambda person_id, kind, **kw: calls.append(person_id))
    with api_tx() as tx:
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                   'VALUES (%(a)s, %(b)s, FALSE)', dict(a=me['id'], b=liker['id']))
    notify_new_like(liker['id'], me['id'])
    assert calls == []
    with api_tx() as tx:
        tx.execute('DELETE FROM skipped WHERE subject_person_id = %(a)s', dict(a=me['id']))
    notify_new_like(liker['id'], me['id'])
    assert calls == [me['id']]
