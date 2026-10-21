"""The report email is an alert, not a moderation tool (TEC-1845, better
reports plan 2 and 3).

The old Duolicious email carried a YAML dump, the photo links, photo-removal
links and two one-click ban links. The owner (21 Oct 2026) wants none of
that: moderation is done in the dashboard, so the email names the reason,
who reported whom, where and when, and carries one link, to the dashboard.
A report also no longer mints the ban and photo-removal tokens those links
used."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

import antiabuse.lodgereport as lodgereport
from database import api_tx
from tests.unmatch_helpers import converse, match

REPORTER_UUID = '3f9a2c1e-7b6d-4e5f-8a9b-0c1d2e3f4a5b'
REPORTED_UUID = '9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d'
AT = datetime(2026, 10, 21, 14, 5, tzinfo=timezone.utc)


def _report(**over) -> dict:
    row = dict(reporter_id=101, reporter_uuid=REPORTER_UUID, reporter_name='Miriam Levi',
               reported_id=202, reported_uuid=REPORTED_UUID, reported_name='Samuel Cohen',
               message_count=0, reported_at=AT)
    row.update(over)
    return row


def _links(body: str) -> list[str]:
    """Every link a reader can follow (the shell's font stylesheet is not one)."""
    return re.findall(r'<a\s[^>]*href="([^"]+)"', body)


def _dashboard() -> str:
    return (f'https://admin.ahavah.app/?tab=moderation'
            f'&amp;reporter={REPORTER_UUID}&amp;reported={REPORTED_UUID}')


def test_the_body_carries_one_link_to_the_dashboard_and_nothing_else():
    body = lodgereport.report_template(_report(), 'harassment: He would not stop.')

    assert 'ban-link' not in body
    assert 'delete-photo-link' not in body
    assert 'user-images' not in body
    assert _links(body) == [_dashboard()]
    assert 'Open in the dashboard' in body


def test_the_body_says_what_happened_who_where_and_when():
    body = lodgereport.report_template(_report(message_count=12), 'harassment: He would not stop.')

    assert 'Harassment or abusive messages' in body
    assert 'He would not stop.' in body
    assert 'Miriam (member 101) reported Samuel (member 202)' in body
    assert 'From a conversation' in body
    assert '12 messages between them' in body
    assert '21 Oct 2026, 14:05 UTC' in body


def test_a_report_from_a_profile_says_so():
    body = lodgereport.report_template(_report(message_count=0), 'spam-scam')
    assert 'From their profile' in body
    assert '0 messages between them' in body
    assert 'Spam or scam' in body


def test_the_reason_is_escaped():
    body = lodgereport.report_template(
        _report(reporter_name='<b>Eve</b>'), 'other: <script>alert(1)</script> & more')

    assert '<script>' not in body
    assert '&lt;script&gt;alert(1)&lt;/script&gt; &amp; more' in body
    assert '<b>Eve</b>' not in body


@pytest.mark.parametrize('reason, subject', [
    ('inappropriate-photos', 'New report: Inappropriate photos'),
    ('harassment: rude', 'New report: Harassment or abusive messages'),
    ('spam-scam', 'New report: Spam or scam'),
    ('underage', 'New report: Underage user'),
    ('self-harm: worried', 'New report: Self-harm or suicide content'),
    ('other: something else happened', 'New report: Other'),
    ('He kept asking for money', 'New report'),
])
def test_the_subject_names_the_reason(reason, subject):
    assert lodgereport.report_subject(reason, is_automoded_bot=False) == subject
    assert lodgereport.report_subject(reason, is_automoded_bot=True) == subject + ' [automoded]'


def test_a_legacy_reason_is_shown_as_written():
    body = lodgereport.report_template(_report(), 'He kept asking for money')
    assert 'He kept asking for money' in body


def test_the_email_is_sent_with_the_new_subject(monkeypatch):
    sent = []
    monkeypatch.setattr(lodgereport.aws_smtp, 'send', lambda **kw: sent.append(kw))
    lodgereport._send_report_email(reason='underage', report=_report(), is_automoded_bot=False)
    assert sent[0]['subject'] == 'New report: Underage user'
    assert _links(sent[0]['body']) == [_dashboard()]


# ---------------------------------------------------------------------------
# The report itself, through the real route.

@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """The email lodge_report would send, captured on the request thread."""
    calls: list[dict] = []
    monkeypatch.setattr(lodgereport, '_send_report_email', lambda **kw: calls.append(kw))

    class _Now:
        def __init__(self, target, kwargs):
            self.target, self.kwargs = target, kwargs

        def start(self):
            self.target(**self.kwargs)

    monkeypatch.setattr(lodgereport.threading, 'Thread', _Now)
    return calls


def _tokens(*people) -> tuple[int, int]:
    ids = [p['id'] for p in people]
    with api_tx('read committed') as tx:
        bans = tx.execute('SELECT count(*) AS n FROM banned_person_admin_token WHERE person_id = ANY(%(i)s)',
                          dict(i=ids)).fetchone()['n']
        photos = tx.execute(
            """SELECT count(*) AS n FROM deleted_photo_admin_token t
                 JOIN photo ON photo.uuid = t.photo_uuid
                WHERE photo.person_id = ANY(%(i)s)""", dict(i=ids)).fetchone()['n']
    return bans, photos


@pytest.mark.usefixtures('no_limits')
def test_a_report_makes_no_admin_tokens(client, unmatch_pair, captured, add_photo):
    p = unmatch_pair
    add_photo(p.a['id'])
    add_photo(p.b['id'])
    before = _tokens(p.a, p.b)

    r = client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': 'harassment'},
                    headers=p.a_headers)

    assert r.status_code == 200
    assert len(captured) == 1
    assert _tokens(p.a, p.b) == before == (0, 0)


@pytest.mark.usefixtures('no_limits')
def test_a_report_from_a_conversation_counts_the_messages(client, unmatch_pair, captured):
    p = unmatch_pair
    match(p.a, p.b)
    converse(p.a, p.b, 'First')
    converse(p.b, p.a, 'Second')
    converse(p.a, p.b, 'Third')

    client.post(f'/skip/by-uuid/{p.b["uuid"]}', json={'report_reason': 'harassment: rude to me'},
                headers=p.a_headers)

    report = captured[0]['report']
    assert report['reporter_id'] == p.a['id'] and report['reported_id'] == p.b['id']
    assert report['reporter_uuid'] == p.a['uuid'] and report['reported_uuid'] == p.b['uuid']
    assert report['reporter_name'] == 'Hadassah' and report['reported_name'] == 'Samuel'
    assert report['message_count'] == 3
    assert captured[0]['reason'] == 'harassment: rude to me'
    body = lodgereport.report_template(report, captured[0]['reason'])
    assert f'reporter={p.a["uuid"]}&amp;reported={p.b["uuid"]}' in body
    assert '3 messages between them' in body
