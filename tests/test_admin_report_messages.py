"""Show messages, for a report (TEC-1845, better reports plan 3; brief
2026-10-20-admin-report-messages.md).

The report email no longer carries the conversation. Staff open it from the
dashboard instead: GET /admin/reports/messages?reporter=<uuid>&reported=<uuid>
returns the last 25 messages between the two, oldest first, including the
ones held after an unmatch, and writes one audit row each time it is opened.
A message is labelled after the unmatch only when it was sent after
unmatched_pair.unmatched_at; the hold keeps the whole conversation, so
being held says nothing about when a message was sent.
Only a reported pair can be read. Every message here is a test fixture."""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

import antiabuse.lodgereport as lodgereport
from database import api_tx

pytestmark = pytest.mark.usefixtures('no_limits')

ROUTE = '/admin/reports/messages'
_seq = itertools.count()
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(lodgereport, 'lodge_report', lambda **kw: None)


@pytest.fixture
def admin(make_person, sign_in):
    person = make_person(name='Reviewer')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=person['id']))
    yield sign_in(person)
    with api_tx() as tx:
        tx.execute('DELETE FROM admin_audit_log WHERE actor_uuid = %(u)s::uuid', dict(u=person['uuid']))


def _send(sender: dict, recipient: dict, body: str, at: datetime) -> int:
    """One message as the chat server stores it (both archives, the
    erlastic-encoded stanza, the id from the time)."""
    import erlastic

    from service.chat.chatutil import message_string_to_etree
    from service.chat.chatutil.erlang import etree_to_term
    from service.chat.messagestorage.mam import Q_INSERT_MESSAGE, microseconds_to_mam_message_id

    mid = microseconds_to_mam_message_id(int(at.timestamp() * 1_000_000) + next(_seq))
    stanza = message_string_to_etree(message_body=body, to_username=recipient['uuid'],
                                     from_username=sender['uuid'], id=str(uuid4()))
    with api_tx() as tx:
        tx.execute(Q_INSERT_MESSAGE, dict(
            id=mid, to_username=recipient['uuid'], from_username=sender['uuid'],
            message=erlastic.encode(etree_to_term(stanza)), audio_uuid=None,
            search_body=body.lower()))
    return mid


def _hold(*people) -> None:
    """Move these members' archives to the unmatch hold, as an unmatch does."""
    ids = [p['id'] for p in people]
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO unmatched_message (person_id, id, remote_bare_jid, direction, message,
                                              search_body, audio_uuid, held_until)
               SELECT person_id, id, remote_bare_jid, direction, message, search_body, audio_uuid,
                      NOW() + interval '90 days'
                 FROM mam_message WHERE person_id = ANY(%(i)s)""", dict(i=ids))
        tx.execute('DELETE FROM mam_message WHERE person_id = ANY(%(i)s)', dict(i=ids))


def _report(client, p) -> None:
    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': 'harassment'},
                    headers=p.a_headers)
    assert r.status_code == 200


def _get(client, headers, p):
    return client.get(f'{ROUTE}?reporter={p.a["uuid"]}&reported={p.b["uuid"]}', headers=headers)


def _audits(p) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id::text AS id, action, target_email, target_uuid::text AS target_uuid, metadata
                 FROM admin_audit_log
                WHERE action = 'view_report_messages' AND target_uuid = %(u)s::uuid
                ORDER BY created_at""", dict(u=p.b['uuid'])).fetchall()]


def test_staff_only(client, unmatch_pair):
    p = unmatch_pair
    _report(client, p)
    # No session at all: the session decorator refuses it before the route.
    anon = client.get(f'{ROUTE}?reporter={p.a["uuid"]}&reported={p.b["uuid"]}')
    assert anon.status_code in (400, 401)
    assert 'messages' not in (anon.get_json(silent=True) or {})
    assert _get(client, p.a_headers, p).status_code == 403


def test_no_report_no_messages(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    assert _get(client, admin, p).status_code == 404
    # The other way round is a different report.
    _report(client, p)
    r = client.get(f'{ROUTE}?reporter={p.b["uuid"]}&reported={p.a["uuid"]}', headers=admin)
    assert r.status_code == 404


def test_bad_ids_are_refused(client, admin):
    assert client.get(f'{ROUTE}?reporter=nope&reported=nope', headers=admin).status_code == 400
    assert client.get(ROUTE, headers=admin).status_code == 400


def test_the_conversation_oldest_first_with_who_said_it(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Shalom Samuel', T0)
    _send(p.b, p.a, 'Shalom Hadassah', T0 + timedelta(minutes=1))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert body['count'] == 2
    assert [(m['from'], m['first_name'], m['text'], m['after_unmatch']) for m in body['messages']] == [
        ('reporter', 'Hadassah', 'Shalom Samuel', False),
        ('reported', 'Samuel', 'Shalom Hadassah', False),
    ]
    sent = [datetime.fromisoformat(m['sent_at']) for m in body['messages']]
    assert abs(sent[0] - T0) < timedelta(seconds=1)
    assert abs(sent[1] - (T0 + timedelta(minutes=1))) < timedelta(seconds=1)
    assert sent[0].utcoffset() == timedelta(0)


def test_the_last_25_only(client, unmatch_pair, admin):
    p = unmatch_pair
    for i in range(30):
        _send(p.a if i % 2 == 0 else p.b, p.b if i % 2 == 0 else p.a, f'Message {i}',
              T0 + timedelta(minutes=i))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert body['count'] == 25
    assert [m['text'] for m in body['messages']] == [f'Message {i}' for i in range(5, 30)]


def test_messages_held_after_an_unmatch_are_shown_and_not_flagged(client, unmatch_pair, admin):
    """The hold keeps the whole conversation, every word of it sent before
    the unmatch. Being held says nothing about when a message was sent."""
    p = unmatch_pair
    _send(p.a, p.b, 'Before the unmatch', T0)
    _hold(p.a, p.b)
    _send(p.b, p.a, 'Still in the archive', T0 + timedelta(minutes=5))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert [(m['text'], m['after_unmatch']) for m in body['messages']] == [
        ('Before the unmatch', False),
        ('Still in the archive', False),
    ]
    assert body['unmatched_at'] is None


def _unmatch(client, p) -> None:
    from tests.unmatch_helpers import match
    match(p.a, p.b)
    assert client.post(f'/unmatch/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200


def _unmatched_at(p, at: datetime) -> None:
    with api_tx() as tx:
        tx.execute(
            """UPDATE unmatched_pair SET unmatched_at = %(at)s
                WHERE user_a_id = LEAST(%(a)s, %(b)s) AND user_b_id = GREATEST(%(a)s, %(b)s)""",
            dict(at=at, a=p.a['id'], b=p.b['id']))


def test_an_unmatched_conversation_sent_before_the_unmatch_is_not_flagged(client, unmatch_pair, admin):
    """Hannah and Josiah talk, she unmatches, then reports him: nothing he
    sent reads as contact after the unmatch (adversarial A1, GAP-1, SEC-1)."""
    p = unmatch_pair
    for i in range(12):
        _send(p.a if i % 2 == 0 else p.b, p.b if i % 2 == 0 else p.a, f'Message {i}',
              T0 + timedelta(minutes=i))
    _unmatch(client, p)
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert len(body['messages']) == 12
    assert not any(m['after_unmatch'] for m in body['messages'])
    assert body['unmatched_at'] is not None
    assert datetime.fromisoformat(body['unmatched_at']) > T0 + timedelta(minutes=11)


def test_only_a_message_sent_after_the_unmatch_time_is_flagged(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Before', T0)
    _send(p.b, p.a, 'After', T0 + timedelta(minutes=10))
    _unmatch(client, p)
    _unmatched_at(p, T0 + timedelta(minutes=5))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert [(m['text'], m['after_unmatch']) for m in body['messages']] == [
        ('Before', False), ('After', True)]
    assert abs(datetime.fromisoformat(body['unmatched_at']) - (T0 + timedelta(minutes=5))) < timedelta(seconds=1)


@pytest.mark.parametrize('n, more', [(2, False), (25, False), (30, True)])
def test_the_total_and_whether_more_were_left_out(client, unmatch_pair, admin, n, more):
    """The view never states a total it does not know (copy pass row 2)."""
    p = unmatch_pair
    for i in range(n):
        _send(p.a, p.b, f'Message {i}', T0 + timedelta(minutes=i))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert body['count'] == min(n, 25)
    assert body['total'] == n
    assert body['has_more'] is more


def test_the_messages_are_never_cached(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    _report(client, p)

    r = _get(client, admin, p)

    assert r.status_code == 200
    assert 'no-store' in r.headers.get('Cache-Control', '')


def test_the_report_list_counts_messages_without_opening_them(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'One', T0)
    _send(p.b, p.a, 'Two', T0 + timedelta(minutes=1))
    _report(client, p)
    before = len(_audits(p))

    rows = client.get('/admin/reports', headers=admin).get_json()['reports']
    mine = [r for r in rows if r['reporter_uuid'] == p.a['uuid'] and r['reported_uuid'] == p.b['uuid']]

    assert mine and mine[0]['message_count'] == 2
    assert len(_audits(p)) == before


def _email(person: dict) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=person['id'])).fetchone()['email']


def _report_key(client, admin, p) -> str:
    rows = client.get('/admin/reports', headers=admin).get_json()['reports']
    return next(r['report_key'] for r in rows
                if r['reporter_uuid'] == p.a['uuid'] and r['reported_uuid'] == p.b['uuid'])


def test_each_opening_writes_one_audit_row(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    _report(client, p)
    key = _report_key(client, admin, p)
    before = len(_audits(p))

    first = client.get(f'{ROUTE}?reporter={p.a["uuid"]}&reported={p.b["uuid"]}&report={key}'
                       '&from=moderation/reports', headers=admin)
    assert first.status_code == 200
    assert _get(client, admin, p).status_code == 200

    rows = _audits(p)[before:]
    assert len(rows) == 2
    assert rows[0]['target_uuid'] == p.b['uuid']
    assert rows[0]['metadata']['reporter_uuid'] == p.a['uuid']
    assert rows[0]['metadata']['reported_uuid'] == p.b['uuid']
    # Handoff 18: the report, both members and what was shown.
    assert rows[0]['target_email'] == f'{_email(p.a)}, {_email(p.b)}'
    assert rows[0]['metadata']['report_id'] == key
    assert rows[0]['metadata']['messages_shown'] == 1
    assert rows[0]['metadata']['after_unmatching'] == 0
    assert rows[0]['metadata']['opened_from'] == 'moderation/reports'
    # "See the audit entry" opens this row.
    assert first.get_json()['audit_id'] == rows[0]['id']


def test_the_reporter_can_find_the_opening_too(client, unmatch_pair, admin):
    """Both members whose messages were read can find the opening: the
    Target email filter matches either address, and each member's drawer
    lists it (SEC-2)."""
    from service.admin.queries.users import Q_USER_AUDIT_LOG
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    _report(client, p)
    assert _get(client, admin, p).status_code == 200

    for member in (p.a, p.b):
        found = client.get(f'/admin/audit-log?action=view_report_messages&target={_email(member)}&days=0',
                           headers=admin).get_json()['rows']
        assert found, member['uuid']
        with api_tx('read committed') as tx:
            drawer = tx.execute(Q_USER_AUDIT_LOG, dict(uuid=member['uuid'])).fetchall()
        assert any(r['action'] == 'view_report_messages' for r in drawer), member['uuid']


def test_a_report_that_is_not_this_pairs_is_refused(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    _report(client, p)
    before = len(_audits(p))

    r = client.get(f'{ROUTE}?reporter={p.a["uuid"]}&reported={p.b["uuid"]}&report=1-2-20260101000000000000',
                   headers=admin)

    assert r.status_code == 404
    assert len(_audits(p)) == before


def test_a_refused_request_writes_no_audit_row(client, unmatch_pair, admin):
    p = unmatch_pair
    before = len(_audits(p))
    assert _get(client, admin, p).status_code == 404
    assert len(_audits(p)) == before
