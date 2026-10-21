"""Show messages, for a report (TEC-1845, better reports plan 3; brief
2026-10-20-admin-report-messages.md).

The report email no longer carries the conversation. Staff open it from the
dashboard instead: GET /admin/reports/messages?reporter=<uuid>&reported=<uuid>
returns the last 25 messages between the two, oldest first, including the
ones held after an unmatch, and writes one audit row each time it is opened.
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
            """SELECT action, target_uuid::text AS target_uuid, metadata
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


def test_messages_held_after_an_unmatch_are_shown_and_flagged(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Before the unmatch', T0)
    _hold(p.a, p.b)
    _send(p.b, p.a, 'Still in the archive', T0 + timedelta(minutes=5))
    _report(client, p)

    body = _get(client, admin, p).get_json()

    assert [(m['text'], m['after_unmatch']) for m in body['messages']] == [
        ('Before the unmatch', True),
        ('Still in the archive', False),
    ]


def test_each_opening_writes_one_audit_row(client, unmatch_pair, admin):
    p = unmatch_pair
    _send(p.a, p.b, 'Hello there', T0)
    _report(client, p)
    before = len(_audits(p))

    assert _get(client, admin, p).status_code == 200
    assert _get(client, admin, p).status_code == 200

    rows = _audits(p)[before:]
    assert len(rows) == 2
    assert rows[0]['target_uuid'] == p.b['uuid']
    assert rows[0]['metadata']['reporter_uuid'] == p.a['uuid']
    assert rows[0]['metadata']['reported_uuid'] == p.b['uuid']
    assert rows[0]['metadata']['count'] == 1


def test_a_refused_request_writes_no_audit_row(client, unmatch_pair, admin):
    p = unmatch_pair
    before = len(_audits(p))
    assert _get(client, admin, p).status_code == 404
    assert len(_audits(p)) == before
