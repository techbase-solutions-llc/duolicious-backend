"""A member's activity in the admin (TEC-2092, 4 Nov 2026).

GET /admin/users/<uuid>/activity: a timeline, newest first, filtered by
type and paged, with a 7 and 30 day summary. The other member is named for
likes, passes, views and reports. Message text is never read: a test reads
every SQL string the route can run, and another plants words in the archive
and checks they never come back.

Recent activity gains member events in `recent_activity_all` only.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx

_SECRET = 'pomegranate-secret-words'
_MAM_SEQ = [0]


def _get(client, headers, uuid, **args):
    r = client.get(f'/admin/users/{uuid}/activity', headers=headers, query_string=args)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _kinds(data) -> list[str]:
    return [i['kind'] for i in data['items']]


def _archive(owner_id: int, other_uuid: str, direction: str, at: datetime) -> None:
    """One copy of a message in `owner_id`'s archive, carrying text the
    route must never return."""
    _MAM_SEQ[0] += 1
    mam_id = (int(at.timestamp() * 1_000_000) << 8) + (_MAM_SEQ[0] % 200)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO mam_message
                 (id, direction, message, search_body, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, %(d)s, %(m)s, %(s)s, %(p)s, '', %(j)s)""",
            dict(id=mam_id, d=direction, m=_SECRET.encode(), s=_SECRET, p=owner_id, j=other_uuid))


@pytest.fixture
def cleanup():
    """Rows with no foreign key to person, removed after the test."""
    events: list[str] = []
    organisers: list[int] = []
    yield dict(events=events, organisers=organisers)
    with api_tx() as tx:
        tx.execute('DELETE FROM entitlement_event WHERE event_id = ANY(%(e)s)', dict(e=events))
        tx.execute('DELETE FROM organiser WHERE id = ANY(%(o)s)', dict(o=organisers))
        # Feedback outlives its member (person_id is SET NULL), and a left
        # row would sit in the admin's waiting list for other tests.
        tx.execute('DELETE FROM feedback WHERE message = %(s)s', dict(s=_SECRET))


@pytest.fixture
def world(make_person, cleanup):
    """Ruth (the member) and the people she deals with, one line of each
    type, at known times over the last few days."""
    ruth = make_person(name='Ruth Example', gender='Woman')
    david = make_person(name='David Example')
    levi = make_person(name='Levi Example')
    gone = make_person(name='Gone Example')
    now = datetime.now(timezone.utc)

    def ago(hours):
        return now - timedelta(hours=hours)

    with api_tx() as tx:
        p = dict(r=ruth['id'], d=david['id'], l=levi['id'], ru=ruth['uuid'], du=david['uuid'])
        tx.execute("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(r)s, %(d)s, %(t)s)",
                   dict(p, t=ago(50)))
        tx.execute("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(d)s, %(r)s, %(t)s)",
                   dict(p, t=ago(49)))
        tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
                      VALUES (LEAST(%(r)s, %(d)s), GREATEST(%(r)s, %(d)s), %(t)s)""",
                   dict(p, t=ago(49)))
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, created_at)
                      VALUES (%(r)s, %(l)s, %(t)s)""",
                   dict(p, t=(ago(48)).replace(tzinfo=None)))
        tx.execute("""INSERT INTO visited (subject_person_id, object_person_id, updated_at)
                      VALUES (%(r)s, %(l)s, %(t)s), (%(l)s, %(r)s, %(t2)s)""",
                   dict(p, t=ago(47).replace(tzinfo=None), t2=ago(46).replace(tzinfo=None)))
        tx.execute("""INSERT INTO messaged (subject_person_id, object_person_id, created_at)
                      VALUES (%(r)s, %(d)s, %(t)s)""", dict(p, t=ago(45).replace(tzinfo=None)))
        tx.execute("""INSERT INTO person_report (reporter_id, reported_id, reported_at, reason)
                      VALUES (%(r)s, %(l)s, %(t)s, %(s)s), (%(l)s, %(r)s, %(t2)s, %(s)s)""",
                   dict(p, t=ago(30).replace(tzinfo=None), t2=ago(29).replace(tzinfo=None), s=_SECRET))
        tx.execute("""INSERT INTO token_ledger (person_id, delta, reason, metadata, created_at)
                      VALUES (%(ru)s::uuid, 20, 'purchase', '{}'::jsonb, %(t)s),
                             (%(ru)s::uuid, -1, 'reveal_liker',
                              jsonb_build_object('revealed_liker_id', %(du)s::text), %(t2)s)""",
                   dict(p, t=ago(20), t2=ago(19)))
        eid = f'evt_test_{uuid4().hex}'
        cleanup['events'].append(eid)
        tx.execute("""INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
                      VALUES (%(e)s, 'checkout.session.completed', %(r)s::text,
                              '{"livemode": true, "data": {"object": {"mode": "subscription"}}}'::jsonb, %(t)s)""",
                   dict(p, e=eid, t=ago(18)))
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(r)s, %(d1)s, %(t)s, %(t)s)""",
                   dict(p, d1=ago(10).date(), t=ago(10)))
        tx.execute("""INSERT INTO feedback (category, message, person_id, created_at)
                      VALUES ('chat', %(s)s, %(r)s, %(t)s)""", dict(p, s=_SECRET, t=ago(5)))
        tx.execute("""INSERT INTO tool_session (kind, mode, owner_person_id, source, created_at)
                      VALUES ('game', 'us', %(r)s, 'tool:game-us', %(t)s)""", dict(p, t=ago(4)))
        tx.execute("UPDATE person SET sign_up_time = %(t)s WHERE id = %(r)s",
                   dict(p, t=ago(100).replace(tzinfo=None)))
    # Twelve messages with David, both ways, and two with a member who has
    # since deleted their account (their copy goes; Ruth's stays).
    for i in range(12):
        _archive(ruth['id'], david['uuid'], 'O' if i % 2 else 'I', ago(40 - i))
    _archive(ruth['id'], gone['uuid'], 'O', ago(35))
    _archive(ruth['id'], gone['uuid'], 'I', ago(34))
    with api_tx() as tx:
        tx.execute('DELETE FROM person WHERE id = %(g)s', dict(g=gone['id']))
    return dict(ruth=ruth, david=david, levi=levi, now=now)


def test_the_timeline_names_the_other_member_and_counts_messages(client, admin_headers, world):
    data = _get(client, admin_headers, world['ruth']['uuid'])
    assert set(data) == {'summary', 'items', 'next_before'}
    assert data['next_before'] is None
    by_kind: dict[str, list] = {}
    for i in data['items']:
        by_kind.setdefault(i['kind'], []).append(i)
    assert {'like_sent', 'like_received', 'match', 'pass', 'view_given', 'view_received',
            'first_message', 'conversation', 'report_made', 'report_received', 'tokens',
            'reveal', 'premium_started', 'online_week', 'feedback', 'together_started',
            'joined'} <= set(by_kind)
    assert by_kind['like_sent'][0]['other']['name'] == 'David'
    assert by_kind['like_sent'][0]['other']['uuid'] == world['david']['uuid']
    assert by_kind['pass'][0]['other']['name'] == 'Levi'
    assert by_kind['report_received'][0]['other']['name'] == 'Levi'
    assert by_kind['reveal'][0]['other']['name'] == 'David'
    assert by_kind['reveal'][0]['count'] == -1
    assert by_kind['tokens'][0] == {**by_kind['tokens'][0], 'count': 20, 'detail': 'purchase'}
    assert by_kind['feedback'][0]['detail'] == 'chat'
    convos = {(c['other'] or {}).get('name'): c for c in by_kind['conversation']}
    assert convos['David']['count'] == 12
    # The conversation's time is its last message's.
    last = datetime.fromisoformat(convos['David']['at'])
    assert abs((world['now'] - timedelta(hours=29) - last).total_seconds()) < 1
    # A member since deleted: no name, the detail says so.
    assert convos[None]['other'] is None and convos[None]['detail'] == 'deleted'
    assert convos[None]['count'] == 2
    # Newest first.
    ats = [i['at'] for i in data['items']]
    assert ats == sorted(ats, reverse=True)


def test_the_summary_counts_the_last_7_and_30_days(client, admin_headers, world):
    s = _get(client, admin_headers, world['ruth']['uuid'])['summary']
    assert set(s) == {'d7', 'd30'}
    assert set(s['d7']) == {'likes_sent', 'likes_received', 'matches', 'unmatches',
                            'conversations', 'messages_sent', 'views_given',
                            'views_received', 'reports_made', 'reports_received',
                            'days_online'}
    for w in ('d7', 'd30'):
        assert s[w]['likes_sent'] == 1 and s[w]['likes_received'] == 1
        assert s[w]['matches'] == 1 and s[w]['unmatches'] == 0
        # David, and the member since deleted.
        assert s[w]['conversations'] == 2
        assert s[w]['messages_sent'] == 7
        assert s[w]['views_given'] == 1 and s[w]['views_received'] == 1
        assert s[w]['reports_made'] == 1 and s[w]['reports_received'] == 1
        assert s[w]['days_online'] == 1


@pytest.mark.parametrize('kind,expected', [
    ('interactions', {'like_sent', 'like_received', 'match', 'pass', 'view_given', 'view_received'}),
    ('messages', {'first_message', 'conversation'}),
    ('reports', {'report_made', 'report_received'}),
    ('money', {'tokens', 'reveal', 'premium_started'}),
    ('account', {'joined', 'online_week'}),
    ('community', {'feedback', 'together_started'}),
])
def test_each_type_filter_holds_only_its_own_lines(client, admin_headers, world, kind, expected):
    assert set(_kinds(_get(client, admin_headers, world['ruth']['uuid'], type=kind))) == expected


def test_an_unmatch_says_who_did_it_and_keeps_the_match(client, admin_headers, make_person):
    a, b = make_person(name='Anna Unmatch', gender='Woman'), make_person(name='Boaz Unmatch')
    now = datetime.now(timezone.utc)
    with api_tx() as tx:
        tx.execute("""INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by, matched_at, unmatched_at)
                      VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s), %(b)s, %(m)s, %(u)s)""",
                   dict(a=a['id'], b=b['id'], m=now - timedelta(days=2), u=now - timedelta(days=1)))
    items = _get(client, admin_headers, a['uuid'], type='interactions')['items']
    assert [(i['kind'], i['other']['name']) for i in items] == [('unmatched_by', 'Boaz'), ('match', 'Boaz')]
    items = _get(client, admin_headers, b['uuid'], type='interactions')['items']
    assert items[0]['kind'] == 'unmatched'
    s = _get(client, admin_headers, a['uuid'])['summary']['d7']
    assert (s['matches'], s['unmatches']) == (1, 1)


def test_paging_walks_every_line_once_even_when_times_tie(client, admin_headers, make_person):
    me = make_person(name='Pager', gender='Woman')
    others = [make_person(name=f'Liker{i}') for i in range(7)]
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    with api_tx() as tx:
        for i, o in enumerate(others):
            # Three share one time, so a page boundary falls inside a tie.
            at = base if i < 3 else base - timedelta(minutes=i)
            tx.execute("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(o)s, %(m)s, %(t)s)",
                       dict(o=o['id'], m=me['id'], t=at))
    seen, before, pages = [], None, 0
    while True:
        args = dict(type='interactions', limit=2)
        if before:
            args['before'] = before
        data = _get(client, admin_headers, me['uuid'], **args)
        pages += 1
        assert len(data['items']) <= 2
        seen += [i['other']['uuid'] for i in data['items']]
        before = data['next_before']
        if before is None:
            break
        assert pages < 10
    assert pages == 4
    assert sorted(seen) == sorted(o['uuid'] for o in others)
    assert len(set(seen)) == 7


def test_from_and_to_bound_the_timeline(client, admin_headers, make_person):
    me = make_person(name='Dated', gender='Woman')
    o = make_person(name='Other')
    with api_tx() as tx:
        tx.execute("""INSERT INTO liked (liker_id, liked_id, created_at)
                      VALUES (%(m)s, %(o)s, '2026-01-10 15:00+00')""", dict(m=me['id'], o=o['id']))
    assert _kinds(_get(client, admin_headers, me['uuid'], type='interactions',
                       **{'from': '2026-01-10', 'to': '2026-01-10'})) == ['like_sent']
    assert _kinds(_get(client, admin_headers, me['uuid'], type='interactions',
                       **{'from': '2026-01-11'})) == []
    assert _kinds(_get(client, admin_headers, me['uuid'], type='interactions',
                       to='2026-01-09')) == []


def test_bad_input_is_refused(client, admin_headers, make_person):
    me = make_person(name='Bad')
    for args in ({'type': 'gossip'}, {'before': 'yesterday'}, {'from': '10/01/2026'}):
        r = client.get(f"/admin/users/{me['uuid']}/activity", headers=admin_headers, query_string=args)
        assert r.status_code == 400, args
    assert client.get('/admin/users/not-a-uuid/activity', headers=admin_headers).status_code == 404
    assert client.get(f'/admin/users/{uuid4()}/activity', headers=admin_headers).status_code == 404


def test_a_member_cannot_read_it(client, make_person, sign_in):
    me = make_person(name='Nosy')
    r = client.get(f"/admin/users/{me['uuid']}/activity", headers=sign_in(me))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Message text is never read
# ---------------------------------------------------------------------------

# A column of the archive, report or feedback that holds people's words.
# `mam_message` and `unmatched_message` are table names: the lookbehind
# leaves them alone and catches `message` as a column, bare or qualified.
_FORBIDDEN = (
    re.compile(r'(?<![a-z_])message(?![a-z_])'),
    re.compile(r'search_body'),
    re.compile(r'translations'),
    re.compile(r'audio_uuid'),
    re.compile(r'report_reason'),
    re.compile(r'\br\.reason\b'),
    re.compile(r'\bbody\b'),
)


def _every_activity_sql() -> list[str]:
    from service.admin.queries import activity
    from service.admin.queries.overview import _MEMBER_EVENTS
    sqls = [activity.timeline_sql(), activity.Q_MEMBER_ACTIVITY_SUMMARY, _MEMBER_EVENTS]
    sqls += [activity.timeline_sql((t,)) for t in activity.TYPES]
    return sqls


def test_no_activity_sql_selects_message_text():
    sqls = _every_activity_sql()
    # The walk sees the archive at all.
    assert 'mam_message' in sqls[0].lower() and 'unmatched_message' in sqls[1].lower()
    for sql in sqls:
        low = sql.lower()
        for pattern in _FORBIDDEN:
            assert not pattern.search(low), f'activity SQL reads {pattern.pattern}'


def test_the_guard_would_catch_a_body_column():
    """The patterns themselves: a select of the archive's text is caught,
    and the archive's table name alone is not."""
    def caught(sql):
        return any(p.search(sql) for p in _FORBIDDEN)
    assert caught('select mm.message from mam_message mm')
    assert caught('select message from unmatched_message')
    assert caught('select um.search_body from unmatched_message um')
    assert not caught("select mm.id from mam_message mm union all select id from unmatched_message")
    assert not caught("select 'first_message' as kind")


def test_no_words_come_back(client, admin_headers, world):
    """Ruth's archive, her reports and her feedback all hold the planted
    text; the response never does."""
    text = json.dumps(_get(client, admin_headers, world['ruth']['uuid']))
    assert _SECRET not in text


# ---------------------------------------------------------------------------
# The audit log
# ---------------------------------------------------------------------------

def _audit_rows(target_uuid: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT action, target_uuid::text AS target_uuid, metadata FROM admin_audit_log
                WHERE target_uuid = %(u)s::uuid ORDER BY created_at""",
            dict(u=target_uuid)).fetchall()]


def test_opening_the_timeline_is_audited_and_stays_out_of_recent_activity(
        client, admin_headers, make_person):
    me = make_person(name='Watched', gender='Woman')
    others = [make_person(name=f'W{i}') for i in range(3)]
    with api_tx() as tx:
        for o in others:
            tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(o)s, %(m)s)",
                       dict(o=o['id'], m=me['id']))
    first = _get(client, admin_headers, me['uuid'], type='interactions', limit=1)
    rows = _audit_rows(me['uuid'])
    assert [r['action'] for r in rows] == ['view_member_activity']
    assert rows[0]['metadata']['type'] == 'interactions'
    # "Show more" is the same opening: no second row.
    _get(client, admin_headers, me['uuid'], type='interactions', limit=1, before=first['next_before'])
    assert len(_audit_rows(me['uuid'])) == 1
    r = client.get('/admin/overview', headers=admin_headers)
    for feed in ('recent_activity', 'recent_activity_all'):
        assert not [e for e in r.get_json()[feed] if e['object'] == 'view_member_activity'], feed


def test_the_member_panel_leaves_out_timeline_openings(client, admin_headers, make_person):
    """Opening a timeline is audited but never takes a place in the panel's
    "Recent admin actions on this user"; the Audit Log tab still lists it."""
    me = make_person(name='Panel', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO admin_audit_log (actor_email, actor_uuid, action, target_uuid, metadata)
               VALUES ('a@example.com', gen_random_uuid(), 'token_adjust', %(u)s::uuid, '{}'::jsonb)""",
            dict(u=me['uuid']))
    for _ in range(3):
        _get(client, admin_headers, me['uuid'])
    panel = client.get(f"/admin/users/{me['uuid']}", headers=admin_headers).get_json()['audit']
    assert [r['action'] for r in panel] == ['token_adjust']
    rows = client.get('/admin/audit-log?action=view_member_activity&days=0',
                      headers=admin_headers).get_json()['rows']
    assert len([r for r in rows if r['target_uuid'] == me['uuid']]) == 3


# ---------------------------------------------------------------------------
# Recent activity: member events
# ---------------------------------------------------------------------------

def test_member_events_join_the_full_feed_only(client, admin_headers, make_person, cleanup,
                                               published):
    tag = uuid4().hex[:6]
    sarah = make_person(name=f'Sarah{tag} Feed', gender='Woman')
    david = make_person(name=f'David{tag} Feed')
    soon = datetime.now(timezone.utc) + timedelta(minutes=1)
    with api_tx() as tx:
        tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
                      VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s), %(t)s)""",
                   dict(a=sarah['id'], b=david['id'], t=soon))
        tx.execute("UPDATE person SET id_verified_at = %(t)s WHERE id = %(i)s",
                   dict(t=soon, i=sarah['id']))
        tx.execute("UPDATE person SET deletion_requested_at = %(t)s WHERE id = %(i)s",
                   dict(t=soon, i=david['id']))
        eid = f'evt_test_{uuid4().hex}'
        cleanup['events'].append(eid)
        tx.execute("""INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
                      VALUES (%(e)s, 'checkout.session.completed', %(p)s::text,
                              '{"livemode": true, "data": {"object": {"mode": "payment"}}}'::jsonb, %(t)s)""",
                   dict(e=eid, p=david['id'], t=soon))
        oid = tx.execute(
            """INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at,
                                      member_person_id)
               VALUES ('Feed Fellowship', 'fellowship_leader', %(e)s, %(e)s, NOW(), NOW(), %(p)s)
               RETURNING id""",
            dict(e=f'org-{tag}@example.com', p=sarah['id'])).fetchone()['id']
        cleanup['organisers'].append(oid)
    published(dict(id=oid), created_at=soon)

    data = client.get('/admin/overview', headers=admin_headers).get_json()
    mine = {(e['kind'], e['object']): e for e in data['recent_activity_all']
            if e['object'] in (sarah['uuid'], david['uuid'])}
    first_named = sarah if sarah['id'] < david['id'] else david
    match = mine[('match', first_named['uuid'])]
    assert set(match['subject'].split(' and ')) == {f'Sarah{tag}', f'David{tag}'}
    assert ('verified', sarah['uuid']) in mine
    assert ('gathering_created', sarah['uuid']) in mine
    assert ('purchase', david['uuid']) in mine
    assert ('deletion_requested', david['uuid']) in mine
    assert set(mine[('verified', sarah['uuid'])]) == {'kind', 'subject', 'object', 'created_at'}
    # The short feed keeps its five kinds.
    assert {e['kind'] for e in data['recent_activity']} <= {
        'signup_member', 'signup', 'signup_waitlist', 'referral_credited', 'admin_action'}
