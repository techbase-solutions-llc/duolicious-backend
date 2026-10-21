"""The weekly funnel (TEC-1897; frame O.1): likes, matches, first messages
and replies per Barbados week over 12 weeks. Never content."""
from __future__ import annotations

from database import api_tx
from service.admin.queries import community

_SEQ = [0]


def _funnel(client, headers) -> list[dict]:
    r = client.get('/admin/community/funnel', headers=headers)
    assert r.status_code == 200
    return r.get_json()['weeks']


def _message(sender, recipient) -> None:
    _SEQ[0] += 1
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(s)s AS id",
            dict(s=(_SEQ[0] + 100) % 256)).fetchone()['id']
        for direction, owner, other in (('O', sender, recipient), ('I', recipient, sender)):
            tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                          VALUES (%(id)s, %(d)s, ''::bytea, %(p)s, '', %(j)s)""",
                       dict(id=mam_id + (direction == 'I'), d=direction, p=owner['id'], j=other['uuid']))


def test_twelve_weeks_oldest_first_ending_this_week(client, admin_bearer):
    weeks = _funnel(client, admin_bearer)
    assert len(weeks) == 12
    with api_tx('read committed') as tx:
        this_monday = tx.execute(
            "SELECT date_trunc('week', (NOW() AT TIME ZONE 'America/Barbados'))::date AS d").fetchone()['d']
    assert weeks[-1]['week_start'] == this_monday.isoformat()
    assert weeks == sorted(weeks, key=lambda w: w['week_start'])


def test_this_weeks_likes_match_first_message_and_reply(client, admin_bearer, make_person):
    a, b = make_person(name='FunA'), make_person(name='FunB')
    before = _funnel(client, admin_bearer)[-1]
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s), (%(b)s, %(a)s)",
                   dict(a=a['id'], b=b['id']))
        lo, hi = sorted([a['id'], b['id']])
        tx.execute("INSERT INTO ahavah_match (user_a_id, user_b_id) VALUES (%(a)s, %(b)s)",
                   dict(a=lo, b=hi))
    _message(a, b)
    _message(a, b)  # a second message from the opener is not a reply
    _message(b, a)
    after = _funnel(client, admin_bearer)[-1]
    assert {k: after[k] - before[k] for k in ('likes', 'matches', 'first_messages', 'replies')} == dict(
        likes=2, matches=1, first_messages=1, replies=1)


def test_the_week_is_the_barbados_week(client, admin_bearer, make_person):
    a, b = make_person(name='FunC'), make_person(name='FunD')
    weeks_before = _funnel(client, admin_bearer)
    with api_tx() as tx:
        # Sunday 23:00 in Barbados is Monday 03:00 UTC: last week, not this one.
        tx.execute(
            """INSERT INTO liked (liker_id, liked_id, created_at)
               VALUES (%(a)s, %(b)s,
                       (date_trunc('week', NOW() AT TIME ZONE 'America/Barbados') - INTERVAL '1 hour')
                         AT TIME ZONE 'America/Barbados')""",
            dict(a=a['id'], b=b['id']))
    weeks_after = _funnel(client, admin_bearer)
    assert weeks_after[-2]['likes'] - weeks_before[-2]['likes'] == 1
    assert weeks_after[-1]['likes'] == weeks_before[-1]['likes']


def test_staff_likes_are_not_counted(client, admin_bearer, make_person):
    staff, member = make_person(name='FunStaff'), make_person(name='FunMem')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = _funnel(client, admin_bearer)[-1]['likes']
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=staff['id'], b=member['id']))
    assert _funnel(client, admin_bearer)[-1]['likes'] == before


def test_the_funnel_reads_no_content():
    low = community.Q_WEEKLY_FUNNEL.lower()
    for forbidden in ('m.message', 'search_body', 'translations', 'audio_uuid'):
        assert forbidden not in low
