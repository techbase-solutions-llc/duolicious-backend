"""Moderation still works after an unmatch (TEC-1845, migration 0070):
either person can report the other, the report carries the conversation from
the hold, and unblocking a report never undoes the unmatch."""
from __future__ import annotations

import pytest

import antiabuse.lodgereport as lodgereport
from antiabuse.sql import Q_LAST_MESSAGES
from database import api_tx
from tests.unmatch_helpers import converse, match

pytestmark = pytest.mark.usefixtures('no_limits')

REASON = 'Harassment: messages after we stopped talking'


@pytest.fixture
def lodged(monkeypatch) -> list[dict]:
    """The report email, captured instead of sent."""
    calls: list[dict] = []
    monkeypatch.setattr(lodgereport, 'lodge_report', lambda **kw: calls.append(kw))
    return calls


def _unmatch(client, p) -> None:
    assert client.post(f'/unmatch/by-uuid/{p.b["uuid"]}', headers=p.a_headers).status_code == 200


def _reported(subject: dict, obj: dict) -> bool:
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT reported FROM skipped
                WHERE subject_person_id = %(s)s AND object_person_id = %(o)s""",
            dict(s=subject['id'], o=obj['id'])).fetchone()
    return bool(row and row['reported'])


@pytest.mark.parametrize('reporter', ['a', 'b'])
def test_either_can_still_report_the_other(client, unmatch_pair, lodged, reporter):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)
    me, other, headers = (p.a, p.b, p.a_headers) if reporter == 'a' else (p.b, p.a, p.b_headers)

    r = client.post(f'/skip/by-uuid/{other["uuid"]}', json={'report_reason': REASON}, headers=headers)

    assert r.status_code == 200
    assert _reported(me, other)
    assert [c['object_uuid'] for c in lodged] == [other['uuid']]


def test_the_report_email_carries_the_held_conversation(client, unmatch_pair):
    p = unmatch_pair
    match(p.a, p.b)
    converse(p.a, p.b, 'First')
    converse(p.b, p.a, 'Second')
    _unmatch(client, p)

    with api_tx('read committed') as tx:
        rows = tx.execute(Q_LAST_MESSAGES, dict(subject_uuid=p.b['uuid'], object_uuid=p.a['uuid'])).fetchall()

    assert [(r['sent_by'], r['search_body']) for r in rows] == [('accused', 'first'), ('reporter', 'second')]


def test_unblocking_a_report_never_undoes_the_unmatch(client, unmatch_pair, lodged):
    p = unmatch_pair
    match(p.a, p.b)
    _unmatch(client, p)
    client.post(f'/skip/by-uuid/{p.a["uuid"]}', json={'report_reason': REASON}, headers=p.b_headers)
    assert [x['uuid'] for x in client.get('/blocked', headers=p.b_headers).get_json()] == [p.a['uuid']]

    assert client.post(f'/unskip/by-uuid/{p.a["uuid"]}', headers=p.b_headers).status_code == 200

    with api_tx('read committed') as tx:
        assert tx.execute('SELECT is_blocked_pair(%(a)s, %(b)s) AS v',
                          dict(a=p.a['id'], b=p.b['id'])).fetchone()['v'] is True
    assert client.get('/matches', headers=p.b_headers).get_json()['matches'] == []


def test_a_report_made_before_the_unmatch_still_stands(client, unmatch_pair, lodged):
    p = unmatch_pair
    match(p.a, p.b)
    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': REASON}, headers=p.a_headers)

    _unmatch(client, p)

    assert _reported(p.a, p.b)
    assert client.get('/blocked', headers=p.a_headers).get_json()[0]['uuid'] == p.b['uuid']
