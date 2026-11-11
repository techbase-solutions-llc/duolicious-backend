"""A pass from Liked you sticks (11 Nov 2026).

The web posts a plain "nope" from Liked you, and Q_LIST_INCOMING_LIKES
kept plain passes on purpose (migration 0035: a pass must not erase a
like). So the card came back on reload and stayed in the likes count and
the Matches badge (both read /likes/incoming's count). Now a pass made
after the like arrived answers that like: it leaves Liked you and the
counts. A pass made before the like came in does not hide the later like.
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


def test_a_pass_before_the_like_does_not_hide_it(client, pair):
    me, liker, h = pair
    _pass(client, h, liker)
    _like(liker, me, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert _incoming(client, h) == (1, {liker['uuid']})


@pytest.mark.parametrize('module,name,me,liker,liked_at', [
    ('emails.likes_waiting_weekly', '_Q_DUE', 'l.liked_id', 'l.liker_id', 'l.created_at'),
    ('emails.send_likes_waiting', '_Q_TARGETS', 'p.id', 'l.liker_id', 'l.created_at'),
    ('emails.send_community_weekly', '_Q_PERSONAL', 'p.id', 'l.liker_id', 'l.created_at'),
])
def test_the_likes_waiting_emails_leave_out_an_answered_like(module, name, me, liker, liked_at):
    """The emails that count likes waiting read the same rule."""
    import importlib
    import re
    from service.decisions.answered import passed_after_like_sql
    mod = importlib.import_module(module)
    texts = [getattr(mod, name)] if name else [v for v in vars(mod).values() if isinstance(v, str)]
    squash = lambda t: re.sub(r'\s+', ' ', t)
    assert any(squash(passed_after_like_sql(me, liker, liked_at)) in squash(t) for t in texts)
