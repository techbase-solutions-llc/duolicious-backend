"""A report must say what happened (TEC-1845, better reports plan 1).

The first member report (20 Oct 2026) was a bare "Other" with no words, so it
told the owner nothing. The app stores `<category>` or `<category>: <details>`.
An "other" report now needs at least 10 characters of details; the app checks
too, but its check can be bypassed and older installs do not have it. The
other categories keep details optional, and free text from old clients that
does not start with a category is still accepted."""
from __future__ import annotations

import pytest

import antiabuse.lodgereport as lodgereport
from database import api_tx

pytestmark = pytest.mark.usefixtures('no_limits')

REFUSAL = {'error': 'Write at least 10 characters so we know what happened.'}


@pytest.fixture(autouse=True)
def lodged(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(lodgereport, 'lodge_report', lambda **kw: calls.append(kw))
    return calls


def _reported(p) -> bool:
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT reported FROM skipped
                WHERE subject_person_id = %(s)s AND object_person_id = %(o)s""",
            dict(s=p.a['id'], o=p.b['id'])).fetchone()
    return bool(row and row['reported'])


@pytest.mark.parametrize('reason', ['other', 'Other', 'other: ', 'other:   too short ', 'other: 123456789'])
def test_a_bare_other_is_refused(client, unmatch_pair, lodged, reason):
    p = unmatch_pair
    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': reason}, headers=p.a_headers)

    assert r.status_code == 400
    assert r.get_json() == REFUSAL
    assert not _reported(p)
    assert lodged == []


@pytest.mark.parametrize('reason', [
    'other: He asked me for my bank details.',
    'other: 1234567890',
    'harassment',
    'spam-scam',
    'inappropriate-photos: ',
    'He kept asking for money',  # an old client's free text
])
def test_a_report_that_says_enough_is_accepted(client, unmatch_pair, lodged, reason):
    p = unmatch_pair
    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': reason}, headers=p.a_headers)

    assert r.status_code == 200
    assert _reported(p)
    assert len(lodged) == 1


def test_a_plain_pass_needs_no_reason(client, unmatch_pair, lodged):
    p = unmatch_pair
    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={}, headers=p.a_headers)
    assert r.status_code == 200
    assert lodged == []
