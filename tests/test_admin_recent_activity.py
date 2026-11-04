"""Recent activity shows what changed (TEC-2091, 4 Nov 2026).

- Audit actions that only look (an admin opening the member map, or a
  report's messages) stay in the audit log and leave both feeds. On 4 Nov,
  61 of the log's 155 rows were map views, pushing real events out.
- Member feedback joins `recent_activity_all` as the kind `feedback`: the
  category and the row's id, never the message, the email or the member.
  `recent_activity` keeps its five kinds, since an admin fails on a kind it
  does not know.
"""
from __future__ import annotations

import json
from uuid import uuid4

from database import api_tx

_ORIGINAL_KINDS = {'signup_member', 'signup', 'signup_waitlist', 'referral_credited', 'admin_action'}


def _overview(client, headers) -> dict:
    r = client.get('/admin/overview', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _audit_row(action: str, actor: str) -> None:
    """An audit row a minute in the future, so it heads the feed if the feed
    lets it in at all."""
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO admin_audit_log (actor_email, actor_uuid, action, metadata, created_at)
               VALUES (%(e)s, gen_random_uuid(), %(a)s, %(m)s::jsonb, NOW() + INTERVAL '1 minute')""",
            dict(e=actor, a=action, m=json.dumps({})))


def test_views_leave_both_feeds_and_a_change_stays(client, admin_headers):
    actor = f'viewer-{uuid4().hex[:8]}@example.com'
    _audit_row('token_adjust', actor)
    _audit_row('admin_map_view', actor)
    _audit_row('view_report_messages', actor)
    data = _overview(client, admin_headers)
    for feed in ('recent_activity', 'recent_activity_all'):
        mine = [e['object'] for e in data[feed]
                if e['kind'] == 'admin_action' and e['subject'] == actor]
        assert mine == ['token_adjust'], feed


def test_opening_the_map_is_still_audited_but_not_in_the_feed(client, admin_headers):
    r = client.get('/admin/map', headers=admin_headers)
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT 1 FROM admin_audit_log
                WHERE action = 'admin_map_view' AND created_at > NOW() - INTERVAL '1 minute'""").fetchone()
    assert row is not None
    data = _overview(client, admin_headers)
    for feed in ('recent_activity', 'recent_activity_all'):
        assert not [e for e in data[feed] if e['object'] == 'admin_map_view'], feed


def test_feedback_is_in_the_full_feed_as_its_category_only(client, admin_headers, make_person):
    name = f'Feedbacker {uuid4().hex[:6]}'
    member = make_person(name=name)
    secret = f'private words {uuid4().hex}'
    email = f'fb-{uuid4().hex[:8]}@example.com'
    with api_tx() as tx:
        fid = tx.execute(
            """INSERT INTO feedback (category, message, email, person_id, created_at)
               VALUES ('problem', %(m)s, %(e)s, %(p)s, NOW() + INTERVAL '1 minute')
               RETURNING id""",
            dict(m=secret, e=email, p=member['id'])).fetchone()['id']
    try:
        data = _overview(client, admin_headers)
        rows = [e for e in data['recent_activity_all'] if e['kind'] == 'feedback']
        assert rows and rows[0]['subject'] == 'problem' and rows[0]['object'] == str(fid)
        assert set(rows[0]) == {'kind', 'subject', 'object', 'created_at'}
        # The member is in the feed anyway, as a new account; the feedback
        # rows are what must not name them.
        text = json.dumps(rows)
        assert secret not in json.dumps(data) and secret not in text and email not in text and name not in text
        # The original feed keeps its five kinds.
        assert {e['kind'] for e in data['recent_activity']} <= _ORIGINAL_KINDS
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM feedback WHERE id = %(i)s', dict(i=fid))
