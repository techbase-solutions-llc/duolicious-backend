"""The mentor's read-only view (TEC-1845, section 7).

Owner's answer, 21 Oct 2026, item 30: a mentor sees only messages sent
after the single shares the conversation, never the history before it.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

_seq = itertools.count()


@pytest.fixture
def chat_messages():
    """chat_messages(sender, recipient, body=None, *, audio_uuid=None, at=None)
    -> id: one message stored as process_store_mam_message_batch stores it
    (both archives, the erlastic-encoded stanza, the id from the time)."""
    import erlastic

    from service.chat.chatutil import message_string_to_etree
    from service.chat.messagestorage.mam import Q_INSERT_MESSAGE, microseconds_to_mam_message_id
    from service.chat.chatutil.erlang import etree_to_term

    def _send(sender, recipient, body=None, *, audio_uuid=None, at=None) -> int:
        at = at or datetime.now(timezone.utc)
        micros = int(at.timestamp() * 1_000_000) + next(_seq)
        mid = microseconds_to_mam_message_id(micros)
        stanza = message_string_to_etree(message_body=body, to_username=recipient['uuid'],
                                         from_username=sender['uuid'], id=str(uuid4()))
        with api_tx() as tx:
            tx.execute(Q_INSERT_MESSAGE, dict(
                id=mid, to_username=recipient['uuid'], from_username=sender['uuid'],
                message=erlastic.encode(etree_to_term(stanza)), audio_uuid=audio_uuid,
                search_body=(body or '').lower()))
        return mid

    return _send


@pytest.fixture
def invited_mentor(make_person):
    """invited_mentor() -> (link, token): Rivka has invited Ruth, who has not
    accepted yet. The mentor account a test makes goes afterwards."""
    from service.leads import new_token
    addresses: list[str] = []

    def _make(expires_in=timedelta(days=14)):
        single = make_person(name='Rivka Levi', gender='Woman')
        address = f'ruth.{uuid4().hex[:8]}@ahavah-test.invalid'
        addresses.append(address)
        token, hashed = new_token()
        with api_tx() as tx:
            lid = tx.execute(
                """INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, relation,
                                            invite_token_hash, invite_expires_at)
                   VALUES (%(s)s, %(e)s, %(e)s, 'parent', %(h)s, NOW() + %(x)s) RETURNING id""",
                dict(s=single['id'], e=address, h=hashed, x=expires_in)).fetchone()['id']
        return dict(id=lid, single_id=single['id'], single_uuid=single['uuid'], email=address), token

    yield _make
    with api_tx() as tx:
        tx.execute('UPDATE mentor_link SET revoked_at = COALESCE(revoked_at, NOW()) '
                   'WHERE mentor_normalized_email = ANY(%(e)s)', dict(e=addresses))
        tx.execute('DELETE FROM mentor_account WHERE normalized_email = ANY(%(e)s)', dict(e=addresses))


@pytest.fixture
def mentor_session(single_with_mentor):
    """mentor_session() -> (m, h_single, h_mentor): single_with_mentor with a
    signed-in mentor. m has single, match, single_uuid, match_uuid, h_match."""
    from service.matchmaker.mentor_view import _issue

    def _make():
        single, match, h_single, h_match = single_with_mentor()
        with api_tx() as tx:
            token = _issue(tx, single['mentor_account_id'], datetime.now(timezone.utc))['token']
        m = dict(single=single, match=match, single_uuid=single['uuid'], match_uuid=match['uuid'],
                 h_match=h_match)
        return m, h_single, {'X-Mentor-Token': token}
    return _make


def _conversation(client, m, h_mentor, before=None):
    q = f'?before={before}' if before else ''
    return client.get(f"/mentor/singles/{m['single_uuid']}/matches/{m['match_uuid']}/conversation{q}",
                      headers=h_mentor)


def test_the_invitation_link_signs_the_mentor_in(client, invited_mentor):
    link, token = invited_mentor()
    look = client.get(f'/mentor/invites/{token}')
    assert look.status_code == 200 and look.get_json() == {'single_first_name': 'Rivka', 'email': link['email']}
    r = client.post('/mentor/session', json=dict(invite_token=token))
    assert r.status_code == 201, r.get_data(as_text=True)
    me = client.get('/mentor/me', headers={'X-Mentor-Token': r.get_json()['token']}).get_json()
    assert me == {'singles': [{'uuid': link['single_uuid'], 'first_name': 'Rivka'}], 'ended': []}
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT confirmed_at, mentor_account_id FROM mentor_link WHERE id = %(i)s',
                         dict(i=link['id'])).fetchone()
    assert row['confirmed_at'] is not None and row['mentor_account_id'] is not None
    # The link signs in once.
    assert client.post('/mentor/session', json=dict(invite_token=token)).status_code == 403


def test_an_expired_invitation_says_so(client, invited_mentor):
    _link, token = invited_mentor(expires_in=timedelta(minutes=-1))
    assert client.get(f'/mentor/invites/{token}').status_code == 410
    r = client.post('/mentor/session', json=dict(invite_token=token))
    assert r.status_code == 410 and r.get_json()['error'] == 'expired'


def test_a_message_from_before_the_share_is_never_returned(client, mentor_session, chat_messages):
    """Owner's answer, item 30."""
    m, h_single, h_mentor = mentor_session()
    single, match = m['single'], m['match']
    chat_messages(single, match, 'Before sharing, from Rivka', at=datetime.now(timezone.utc) - timedelta(minutes=5))
    chat_messages(match, single, 'Before sharing, from Samuel', at=datetime.now(timezone.utc) - timedelta(minutes=4))
    assert client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single).status_code == 200
    chat_messages(single, match, 'After sharing', at=datetime.now(timezone.utc) + timedelta(seconds=1))
    body = _conversation(client, m, h_mentor).get_json()
    texts = [x.get('text') for x in body['messages']]
    assert texts == ['After sharing']
    assert not any('Before sharing' in (t or '') for t in texts)


def test_a_gap_between_two_shares_stays_unread(client, mentor_session, chat_messages):
    m, h_single, h_mentor = mentor_session()
    single, match = m['single'], m['match']
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    chat_messages(single, match, 'First share', at=datetime.now(timezone.utc) + timedelta(seconds=1))
    with api_tx() as tx:
        tx.execute("""UPDATE shared_conversation SET shared_at = shared_at - interval '1 hour',
                             revoked_at = NOW() - interval '30 minutes'
                       WHERE single_person_id = %(s)s""", dict(s=single['id']))
    chat_messages(single, match, 'While not shared', at=datetime.now(timezone.utc) - timedelta(minutes=10))
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    chat_messages(match, single, 'Second share', at=datetime.now(timezone.utc) + timedelta(seconds=2))
    texts = [x.get('text') for x in _conversation(client, m, h_mentor).get_json()['messages']]
    assert 'While not shared' not in texts and texts[-1] == 'Second share'


def test_a_mentor_reaches_only_what_was_shared(client, mentor_session, make_person, single_with_mentor):
    m, h_single, h_mentor = mentor_session()
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    assert _conversation(client, m, h_mentor).status_code == 200
    other_match = make_person(name='Other Match', gender='Man')
    with api_tx() as tx:
        tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                   'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                   dict(a=m['single']['id'], b=other_match['id']))
    r = client.get(f"/mentor/singles/{m['single_uuid']}/matches/{other_match['uuid']}/conversation", headers=h_mentor)
    assert r.status_code == 403 and r.get_json()['error'] == 'not_shared'
    stranger = make_person(name='Stranger')
    r = client.get(f"/mentor/singles/{m['single_uuid']}/matches/{stranger['uuid']}/conversation", headers=h_mentor)
    assert r.status_code == 404
    another, _match, _hs, _hm = single_with_mentor('Naomi Levi')
    r = client.get(f"/mentor/singles/{another['uuid']}/matches", headers=h_mentor)
    assert r.status_code == 410 and r.get_json()['error'] == 'access_ended'
    assert client.get('/mentor/singles/not-a-uuid/matches', headers=h_mentor).status_code == 410
    listed = client.get(f"/mentor/singles/{m['single_uuid']}/matches", headers=h_mentor).get_json()['matches']
    shared = {x['uuid']: x['shared'] for x in listed}
    assert shared[m['match_uuid']] is True and shared[other_match['uuid']] is False


def test_a_removed_mentor_sees_nothing_at_once(client, mentor_session):
    m, h_single, h_mentor = mentor_session()
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    client.delete('/mentor', headers=h_single)
    r = client.get(f"/mentor/singles/{m['single_uuid']}/matches", headers=h_mentor)
    assert r.status_code == 410 and r.get_json()['error'] == 'access_ended'
    assert _conversation(client, m, h_mentor).status_code == 410
    assert client.get('/mentor/me', headers=h_mentor).get_json()['ended'] == [{'first_name': 'Rivka'}]


def test_sharing_stopped_while_open(client, mentor_session):
    m, h_single, h_mentor = mentor_session()
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    client.delete(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    r = _conversation(client, m, h_mentor)
    assert r.status_code == 403 and r.get_json()['error'] == 'not_shared'


def test_the_conversation_is_read_only_text_and_says_who_wrote(client, mentor_session, chat_messages):
    m, h_single, h_mentor = mentor_session()
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    chat_messages(m['single'], m['match'], 'Shalom Samuel', at=later)
    chat_messages(m['match'], m['single'], None, audio_uuid='a' * 32, at=later + timedelta(seconds=1))
    body = _conversation(client, m, h_mentor).get_json()
    assert [(x['from'], x.get('text'), x['voice']) for x in body['messages']] == [
        ('single', 'Shalom Samuel', False), ('match', None, True)]
    assert body['single_first_name'] == 'Rivka' and body['match_first_name'] == 'Samuel'
    assert 'text' not in body['messages'][1]
    # Nowhere to write: no route takes a message from a mentor.
    assert client.post(f"/mentor/singles/{m['single_uuid']}/matches/{m['match_uuid']}/conversation",
                       headers=h_mentor, json=dict(text='hi')).status_code == 405


def test_pages_go_back_fifty_at_a_time(client, mentor_session, chat_messages):
    m, h_single, h_mentor = mentor_session()
    client.post(f"/conversations/{m['match_uuid']}/share", headers=h_single)
    start = datetime.now(timezone.utc) + timedelta(seconds=1)
    for i in range(55):
        chat_messages(m['single'], m['match'], f'm{i}', at=start + timedelta(milliseconds=i))
    first = _conversation(client, m, h_mentor).get_json()['messages']
    assert len(first) == 50 and first[-1]['text'] == 'm54' and first[0]['text'] == 'm5'
    older = _conversation(client, m, h_mentor, before=first[0]['id']).get_json()['messages']
    assert [x['text'] for x in older] == ['m0', 'm1', 'm2', 'm3', 'm4']


def test_a_note_is_seen_by_the_single_and_never_by_the_match(client, mentor_session):
    m, h_single, h_mentor = mentor_session()
    r = client.put(f"/mentor/singles/{m['single_uuid']}/notes/{m['match_uuid']}", headers=h_mentor,
                   json=dict(note='Ask about his family.'))
    assert r.status_code == 200 and r.get_json() == {'saved': True}
    detail = client.get(f"/mentor/singles/{m['single_uuid']}/matches/{m['match_uuid']}", headers=h_mentor).get_json()
    assert detail['note'] == 'Ask about his family.' and detail['first_name'] == 'Samuel'
    assert client.get(f"/matches/{m['match_uuid']}/mentor-note", headers=h_single).get_json() == \
        {'note': 'Ask about his family.'}
    assert client.get(f"/matches/{m['single_uuid']}/mentor-note", headers=m['h_match']).status_code == 404
    client.put(f"/mentor/singles/{m['single_uuid']}/notes/{m['match_uuid']}", headers=h_mentor, json=dict(note=''))
    assert client.get(f"/matches/{m['match_uuid']}/mentor-note", headers=h_single).status_code == 404


def test_signing_in_later_takes_the_code_session(client, mentor_session, tool_visitor):
    m, _h_single, _h_mentor = mentor_session()
    _email, h = tool_visitor(m['single']['mentor_email'])
    r = client.post('/mentor/session', headers=h, json={})
    assert r.status_code == 201
    me = client.get('/mentor/me', headers={'X-Mentor-Token': r.get_json()['token']}).get_json()
    assert me['singles'] == [{'uuid': m['single_uuid'], 'first_name': 'Rivka'}]
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM onboardee WHERE email = %(e)s',
                          dict(e=m['single']['mentor_email'])).fetchone() is None


def test_an_address_that_mentors_nobody_cannot_sign_in(client, tool_visitor):
    _email, h = tool_visitor()
    r = client.post('/mentor/session', headers=h, json={})
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_mentor'
    assert client.post('/mentor/session', json={}).status_code == 401


def test_a_bad_or_lapsed_token_is_signed_out(client, mentor_session):
    from service.leads import token_hash
    _m, _h, h_mentor = mentor_session()
    assert client.get('/mentor/me', headers={'X-Mentor-Token': 'x' * 32}).status_code == 401
    assert client.get('/mentor/me').status_code == 401
    with api_tx() as tx:
        tx.execute("UPDATE mentor_session SET expires_at = NOW() - interval '1 minute' WHERE token_hash = %(h)s",
                   dict(h=token_hash(h_mentor['X-Mentor-Token'])))
    assert client.get('/mentor/me', headers=h_mentor).status_code == 401
    client.delete('/mentor/session', headers=h_mentor)


def test_a_mentor_is_never_a_person_and_never_in_search(client, mentor_session, sign_in, make_person):
    m, _h, _hm = mentor_session()
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM person WHERE normalized_email = %(e)s',
                          dict(e=m['single']['mentor_email'])).fetchone() is None
    viewer = sign_in(make_person(name='Searcher'))
    cards = client.get('/search?n=10&o=0', headers=viewer).get_json()
    assert all(c.get('name') != 'Ruth' for c in cards)


def test_closed_until_its_switch(client, mentor_session, invited_mentor, monkeypatch):
    m, h_single, h_mentor = mentor_session()
    _link, token = invited_mentor()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_MENTORS_ENABLED')
    for r in (client.get(f'/mentor/invites/{token}'), client.post('/mentor/session', json=dict(invite_token=token)),
              client.get('/mentor/me', headers=h_mentor), _conversation(client, m, h_mentor),
              client.get(f"/matches/{m['match_uuid']}/mentor-note", headers=h_single),
              client.delete('/mentor/session', headers=h_mentor)):
        assert r.status_code == 404
