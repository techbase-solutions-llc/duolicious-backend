"""Unmatch (TEC-1845, migration 0070): POST /unmatch/by-uuid/<uuid> and
GET /unmatched, from both people's side. The design's promise (follow-ups
export 6.2): "The match and your conversation are removed for both of you,
and you will not see each other in Discover." Discover and every way back
are tests/test_unmatch_no_way_back.py; the chat server is
tests/test_unmatch_chat.py; reporting is tests/test_unmatch_report.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from tests.unmatch_helpers import converse, counts, match

# The profile route reads the quick-question tables (0067).
pytestmark = pytest.mark.usefixtures('no_limits', 'questions_schema')


def _unmatch(client, pair, who: str = 'a'):
    other = pair.b if who == 'a' else pair.a
    headers = pair.a_headers if who == 'a' else pair.b_headers
    return client.post(f'/unmatch/by-uuid/{other["uuid"]}', headers=headers)


def _match_ids(client, headers) -> list[str]:
    body = client.get('/matches', headers=headers).get_json()
    return [m['with_profile']['id'] for m in body['matches']]


def test_the_match_ends_for_both(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    assert p.b['uuid'] in _match_ids(client, p.a_headers)
    assert p.a['uuid'] in _match_ids(client, p.b_headers)

    r = _unmatch(client, p)

    assert r.status_code == 200 and r.get_json() == {'ok': True}
    assert p.b['uuid'] not in _match_ids(client, p.a_headers)
    assert p.a['uuid'] not in _match_ids(client, p.b_headers)
    assert counts(p.a, p.b)['matches'] == 0


def test_the_conversation_is_gone_for_both_and_held_30_days(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    converse(p.a, p.b, 'Shalom')
    converse(p.b, p.a, 'Shalom to you')
    assert counts(p.a, p.b) == dict(archive=4, held=0, inbox=2, messaged=2, matches=1)

    assert _unmatch(client, p).status_code == 200

    assert counts(p.a, p.b) == dict(archive=0, held=4, inbox=0, messaged=0, matches=0)
    with api_tx('read committed') as tx:
        ends = tx.execute(
            """SELECT min(held_until) AS lo, max(held_until) AS hi FROM unmatched_message
                WHERE person_id IN (%(a)s, %(b)s)""",
            dict(a=p.a['id'], b=p.b['id'])).fetchone()
    now = datetime.now(timezone.utc)
    assert now + timedelta(days=29) < ends['lo'] <= ends['hi'] < now + timedelta(days=31)


def test_neither_can_open_the_other(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    sides = ((p.a_headers, p.b), (p.b_headers, p.a))
    for headers, other in sides:
        assert client.get(f'/prospect-profile/{other["uuid"]}', headers=headers).status_code == 200
        assert client.get(f'/conversation-prospect/{other["uuid"]}', headers=headers).status_code == 200

    assert _unmatch(client, p).status_code == 200

    for headers, other in sides:
        assert client.get(f'/prospect-profile/{other["uuid"]}', headers=headers).status_code == 404
        assert client.get(f'/conversation-prospect/{other["uuid"]}', headers=headers).status_code == 404


def test_a_like_left_behind_never_shows_in_the_likes_tabs(client, unmatch_pair):
    """Both likes outlive the unmatch. Once one is taken back the other is a
    plain one-way like, which the likes tabs would list without the barrier."""
    p = unmatch_pair
    match(p.a, p.b)
    assert _unmatch(client, p).status_code == 200
    with api_tx() as tx:
        tx.execute('DELETE FROM liked WHERE liker_id = %(b)s AND liked_id = %(a)s',
                   dict(a=p.a['id'], b=p.b['id']))

    outgoing = client.get('/likes/outgoing', headers=p.a_headers).get_json()['likes']
    incoming = client.get('/likes/incoming', headers=p.b_headers).get_json()['likes']
    assert p.b['uuid'] not in [x['with_profile']['id'] for x in outgoing]
    assert p.a['uuid'] not in [x['with_profile']['id'] for x in incoming]


def test_unmatching_again_from_either_side_succeeds(client, unmatch_pair):
    """6.4's Try again after a lost response, or the other person unmatching
    too, must land on 6.5, not on the failure."""
    p = unmatch_pair
    match(p.a, p.b)
    assert _unmatch(client, p, 'a').status_code == 200
    again = _unmatch(client, p, 'a')
    other_side = _unmatch(client, p, 'b')
    assert (again.status_code, again.get_json()) == (200, {'ok': True})
    assert (other_side.status_code, other_side.get_json()) == (200, {'ok': True})
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT unmatched_by FROM unmatched_pair
                WHERE user_a_id = LEAST(%(a)s, %(b)s) AND user_b_id = GREATEST(%(a)s, %(b)s)""",
            dict(a=p.a['id'], b=p.b['id'])).fetchone()
    assert row['unmatched_by'] == p.a['id']


@pytest.mark.parametrize('target', ['stranger', 'self', 'unknown', 'garbage'])
def test_only_a_match_can_be_unmatched(client, unmatch_pair, target):
    p = unmatch_pair
    uuid = {'stranger': p.b['uuid'], 'self': p.a['uuid'],
            'unknown': '00000000-0000-4000-8000-000000000000', 'garbage': 'not-a-uuid'}[target]

    r = client.post(f'/unmatch/by-uuid/{uuid}', headers=p.a_headers)

    assert (r.status_code, r.get_json()) == (404, {'error': 'not_matched'})
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM unmatched_pair WHERE %(a)s IN (user_a_id, user_b_id)',
                       dict(a=p.a['id'])).fetchone()['n']
    assert n == 0


def test_signed_out_cannot_unmatch(client, unmatch_pair):
    """A session that has ended is 401. No header at all is the auth
    decorator's 400 on every route (service/api/decorators.py); the web
    treats both as 6.4."""
    url = f'/unmatch/by-uuid/{unmatch_pair.b["uuid"]}'
    ended = {'Authorization': 'Bearer not-a-real-session'}
    assert client.post(url, headers=ended).status_code == 401
    assert client.get('/unmatched', headers=ended).status_code == 401
    assert client.post(url).status_code == 400
    assert client.get('/unmatched').status_code == 400
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM unmatched_pair WHERE %(b)s IN (user_a_id, user_b_id)',
                       dict(b=unmatch_pair.b['id'])).fetchone()['n']
    assert n == 0


def test_each_side_lists_the_other_as_unmatched(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    assert client.get('/unmatched', headers=p.a_headers).get_json() == {'uuids': []}

    assert _unmatch(client, p).status_code == 200

    assert client.get('/unmatched', headers=p.a_headers).get_json() == {'uuids': [p.b['uuid']]}
    assert client.get('/unmatched', headers=p.b_headers).get_json() == {'uuids': [p.a['uuid']]}


def test_a_queued_match_email_is_not_sent_and_the_reactions_go(client, unmatch_pair):
    p = unmatch_pair
    mid = match(p.a, p.b)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload, unsub_scope)
               VALUES ('match', %(c)s, %(b)s, 'unmatch-test@example.com', '{}'::jsonb, 'notifications')""",
            dict(c=f'match-{mid}', b=p.b['id']))
        for reactor, peer in ((p.a, p.b), (p.b, p.a)):
            tx.execute(
                """INSERT INTO message_reactions (message_stanza_id, reactor_id, peer_id)
                   VALUES (%(s)s, %(r)s, %(p)s)""",
                dict(s=f'stanza-{reactor["id"]}', r=reactor['id'], p=peer['id']))

    assert _unmatch(client, p).status_code == 200

    with api_tx('read committed') as tx:
        mail = tx.execute(
            """SELECT state, last_error FROM email_outbox
                WHERE campaign = 'match' AND campaign_id = %(c)s""", dict(c=f'match-{mid}')).fetchone()
        reactions = tx.execute(
            'SELECT count(*) AS n FROM message_reactions WHERE reactor_id IN (%(a)s, %(b)s)',
            dict(a=p.a['id'], b=p.b['id'])).fetchone()['n']
    assert dict(mail) == {'state': 'skipped', 'last_error': 'unmatched'}
    assert reactions == 0
