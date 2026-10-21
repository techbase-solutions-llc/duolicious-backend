"""Members someone is waiting on (TEC-1897; frame W.1). Counts per member,
never who liked whom, never what was said."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx
from service.admin.queries import community

_MAM_SEQ = [0]


def _like(a, b, days_ago: int = 0) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO liked (liker_id, liked_id, created_at)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))
                      ON CONFLICT DO NOTHING""", dict(a=a['id'], b=b['id'], d=days_ago))


def _pass(a, b) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id)
                      VALUES (%(a)s, %(b)s) ON CONFLICT DO NOTHING""", dict(a=a['id'], b=b['id']))


def _message(sender, recipient, text: str = 'hello there') -> None:
    """Both archive copies, as the chat service writes them, with real text
    in `message` so the test can prove it never leaves the server."""
    _MAM_SEQ[0] += 1
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(s)s AS id",
            dict(s=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'O', convert_to(%(t)s, 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id, t=text, p=sender['id'], j=recipient['uuid']))
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'I', convert_to(%(t)s, 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id + 1, t=text, p=recipient['id'], j=sender['uuid']))


def _match(a, b, days_ago: int) -> None:
    lo, hi = sorted([a['id'], b['id']])
    with api_tx() as tx:
        tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))""",
                   dict(a=lo, b=hi, d=days_ago))


def _waiting(client, headers) -> dict:
    r = client.get('/admin/community/waiting', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _row(body, person):
    return next((m for m in body['members'] if m['uuid'] == person['uuid']), None)


def test_waiting_is_for_admins_only(client, make_person, sign_in):
    r = client.get('/admin/community/waiting', headers=sign_in(make_person(name='WMember')))
    assert r.status_code == 403


def test_an_unanswered_like_puts_the_liked_member_on_the_list(client, admin_bearer, make_person):
    a, b = make_person(name='WA'), make_person(name='WB')
    before = _waiting(client, admin_bearer)['summary']
    _like(a, b, days_ago=3)
    body = _waiting(client, admin_bearer)
    row = _row(body, b)
    assert row['likes_waiting'] == 1 and row['unanswered_openers'] == 0
    assert row['oldest_wait_at'].endswith('+00:00') and row['last_online_at'].endswith('+00:00')
    assert row['push_on'] is False
    assert _row(body, a) is None
    after = body['summary']
    assert after['likes_waiting'] - before['likes_waiting'] == 1
    assert after['members_with_likes'] - before['members_with_likes'] == 1
    assert after['with_1'] - before['with_1'] == 1


def test_a_pass_or_a_like_back_answers_a_like(client, admin_bearer, make_person):
    a, b, c, d = (make_person(name=n) for n in ('WC', 'WD', 'WE', 'WF'))
    _like(a, b)
    _like(b, a)  # a like back is a match, not a wait
    _like(c, d)
    _pass(d, c)  # a pass is an answer
    body = _waiting(client, admin_bearer)
    assert all(_row(body, p) is None for p in (a, b, c, d))


def test_staff_never_count_as_waiting(client, admin_bearer, make_person):
    staff, member = make_person(name='WStaff'), make_person(name='WMem')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=staff['id']))
    _like(staff, member)
    _like(member, staff)
    _message(staff, member)
    body = _waiting(client, admin_bearer)
    assert _row(body, member) is None and _row(body, staff) is None


def test_a_one_sided_conversation_waits_on_the_recipient(client, admin_bearer, make_person):
    a, b = make_person(name='WG'), make_person(name='WH')
    before = _waiting(client, admin_bearer)['summary']
    _message(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, b)['unanswered_openers'] == 1 and _row(body, a) is None
    assert body['summary']['one_sided'] - before['one_sided'] == 1
    _message(b, a, 'a reply')
    assert _row(_waiting(client, admin_bearer), b) is None


def test_a_silent_match_over_7_days_waits_on_both(client, admin_bearer, make_person):
    a, b = make_person(name='WI'), make_person(name='WJ')
    _match(a, b, days_ago=8)
    body = _waiting(client, admin_bearer)
    assert _row(body, a)['silent_matches'] == 1 and _row(body, b)['silent_matches'] == 1
    _message(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, a) is None and _row(body, b)['unanswered_openers'] == 1


def test_push_and_last_online_are_reported(client, admin_bearer, make_person):
    a, b = make_person(name='WK'), make_person(name='WL')
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - INTERVAL '10 days' WHERE id = %(i)s",
                   dict(i=b['id']))
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, %(e)s, 'k', 'a')""", dict(i=b['id'], e=f'https://push.test/{uuid4()}'))
    before = _waiting(client, admin_bearer)['summary']
    _like(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, b)['push_on'] is True
    assert body['summary']['offline_7d'] - before['offline_7d'] == 1
    assert body['summary']['push_on'] - before['push_on'] == 1


def test_a_blocked_pair_is_never_waiting(client, admin_bearer, make_person):
    a, b, c, d = (make_person(name=n) for n in ('WO', 'WP', 'WQ', 'WR'))
    _message(a, b)
    _match(c, d, days_ago=8)
    before = _waiting(client, admin_bearer)['summary']
    with api_tx() as tx:  # b blocks a, d blocks c: a block is a report
        for s, o in ((b, a), (d, c)):
            tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
                          VALUES (%(s)s, %(o)s, TRUE, 'blocked')""", dict(s=s['id'], o=o['id']))
    body = _waiting(client, admin_bearer)
    assert all(_row(body, p) is None for p in (a, b, c, d))
    assert before['one_sided'] - body['summary']['one_sided'] == 1
    assert before['silent_matches_7d'] - body['summary']['silent_matches_7d'] == 1


def test_no_message_content_is_read_or_returned(client, admin_bearer, make_person):
    for sql in (community.Q_WAITING_SUMMARY, community.Q_WAITING_MEMBERS):
        low = sql.lower()
        for forbidden in ('m.message', 'search_body', 'translations', 'audio_uuid'):
            assert forbidden not in low
    a, b = make_person(name='WM'), make_person(name='WN')
    _message(a, b, 'a very private sentence')
    assert 'private sentence' not in str(_waiting(client, admin_bearer))
