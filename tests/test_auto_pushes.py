"""The 3 automatic pushes of the push composer plan (TEC-2182): likes
waiting, new members near you and the Us game with a match.

Each needs its own switch (off by default), the member's toggle and a push
subscription; none goes to staff, a deleted, deactivated, excluded,
suppressed or unsubscribed member; none goes in quiet hours or a rest
period; each is sent at most once a period; testers hear only about
testers. The payloads never name anyone.

The test database is shared: newcomers are counted in a country code no
real member has, and every check is on the people a test makes.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import held
from service.notifications import auto_pushes as ap

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'switches_on', 'no_limits')

UTC = timezone.utc
COUNTRY = 'QZ'
_SWITCHES = ('AHAVAH_PUSH_LIKES_WAITING_ENABLED', 'AHAVAH_PUSH_NEWCOMERS_ENABLED', 'AHAVAH_PUSH_US_GAME_ENABLED')


@pytest.fixture
def switches_on(monkeypatch):
    for env in _SWITCHES:
        monkeypatch.setenv(env, '1')


@pytest.fixture
def sent(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(ap, '_push', lambda person_id, push, name: out.append(
        dict(push, person_id=person_id, name=name)) or 1)
    monkeypatch.setattr(ap, 'PUSH_READY', lambda: True)
    return out


def _at(hour: int, weekday: int | None = None) -> datetime:
    """Today (or the next given ISO weekday) at `hour` UTC."""
    day = datetime.now(UTC).date()
    if weekday is not None:
        day += timedelta(days=(weekday - day.isoweekday()) % 7)
    return datetime.combine(day, time(hour, 0), UTC)


def _run(job, now) -> int:
    with api_tx() as tx:
        n = job(tx, now)
    held.run_after_commit()
    return n


def _to(sent, person) -> list[dict]:
    return [p for p in sent if p['person_id'] == person['id']]


def _sql(q, **params):
    with api_tx() as tx:
        tx.execute(q, params)


def _pref(person, column, value):
    _sql(f"""INSERT INTO notification_preference (person_id, {column}) VALUES (%(p)s, %(v)s)
             ON CONFLICT (person_id) DO UPDATE SET {column} = %(v)s""", p=person['id'], v=value)


def _logged(person, campaign):
    with api_tx('read committed') as tx:
        return [r['campaign_id'] for r in tx.execute(
            "SELECT campaign_id FROM push_send_log WHERE person_id = %(p)s AND campaign = %(c)s",
            dict(p=person['id'], c=campaign)).fetchall()]


def _no_name(push, *names):
    text = f"{push['title']} {push['body']}"
    for n in names:
        assert n.lower() not in text.lower()


# ---------------------------------------------------------------------------
# Likes waiting
# ---------------------------------------------------------------------------

@pytest.fixture
def liked(push_member, make_person):
    """liked() -> (member, liker): a like 5 days old, the member away 10
    days, likes push on."""
    def _make(*, member_name='Ruth', liker_name='Boaz', days_ago=5, liker_gender='Man', tz='UTC'):
        m = push_member(member_name, gender='Woman', online_days_ago=10, tz=tz)
        liker = make_person(name=liker_name, gender=liker_gender,
                            email=f'{liker_name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
        _pref(m, 'push_likes', True)
        _sql("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))",
             a=liker['id'], b=m['id'], d=days_ago)
        return m, liker
    return _make


def test_a_waiting_like_is_pushed_once_a_week_and_names_nobody(liked, sent):
    m, liker = liked()
    now = _at(15)
    assert _run(ap.queue_likes_waiting, now) >= 1
    _run(ap.queue_likes_waiting, now + timedelta(hours=1))
    pushes = _to(sent, m)
    assert len(pushes) == 1
    p = pushes[0]
    assert (p['title'], p['body']) == ('Someone likes you', 'You have a like waiting. Open Ahavah to see it.')
    assert p['url'] == '/matches?tab=likes&src=lwpush' and p['name'] == 'likes_waiting_push'
    _no_name(p, 'Boaz')
    assert len(_logged(m, ap.LIKES_WAITING)) == 1


def test_no_likes_push_for_an_answered_or_unseen_like(liked, sent, push_member):
    cases = []
    back, l1 = liked(member_name='Back', liker_name='LikerBack')
    _sql("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)", a=back['id'], b=l1['id'])
    cases.append(back)
    passed, l2 = liked(member_name='Passed', liker_name='LikerPassed')
    _sql("INSERT INTO skipped (subject_person_id, object_person_id) VALUES (%(a)s, %(b)s)", a=passed['id'], b=l2['id'])
    cases.append(passed)
    matched, l3 = liked(member_name='Matched', liker_name='LikerMatched')
    _sql("INSERT INTO ahavah_match (user_a_id, user_b_id) VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))",
         a=matched['id'], b=l3['id'])
    cases.append(matched)
    young, _ = liked(member_name='Young', liker_name='LikerYoung', days_ago=1)
    cases.append(young)
    seen, _ = liked(member_name='Seen', liker_name='LikerSeen')
    _sql("UPDATE person SET last_online_time = NOW() - interval '1 day' WHERE id = %(i)s", i=seen['id'])
    cases.append(seen)
    same, _ = liked(member_name='Same', liker_name='LikerSame', liker_gender='Woman')
    cases.append(same)
    split, l7 = liked(member_name='Split', liker_name='LikerTester')
    _sql("UPDATE person SET roles = ARRAY['tester']::text[] WHERE id = %(i)s", i=l7['id'])
    cases.append(split)
    staff, _ = liked(member_name='Staffer', liker_name='LikerStaff')
    _sql("UPDATE person SET roles = ARRAY['mod']::text[] WHERE id = %(i)s", i=staff['id'])
    cases.append(staff)
    off, _ = liked(member_name='Off', liker_name='LikerOff')
    _pref(off, 'push_likes', False)
    cases.append(off)
    gone, l10 = liked(member_name='Gone', liker_name='LikerGone')
    _sql("UPDATE person SET admin_deactivated_at = NOW() WHERE id = %(i)s", i=l10['id'])
    cases.append(gone)
    _run(ap.queue_likes_waiting, _at(15))
    for m in cases:
        assert _to(sent, m) == [], m


def test_the_likes_push_waits_for_its_hours_and_for_7_days(liked, sent):
    early, _ = liked(member_name='Early', liker_name='LikerEarly')
    _run(ap.queue_likes_waiting, _at(9))           # 09:00 in UTC: not quiet, before 10:00
    assert _to(sent, early) == []
    night, _ = liked(member_name='Night', liker_name='LikerNight', tz='Pacific/Honolulu')
    _run(ap.queue_likes_waiting, _at(15))           # 05:00 in Honolulu
    assert _to(sent, night) == []
    assert len(_to(sent, early)) == 1
    recent, _ = liked(member_name='Recent', liker_name='LikerRecent')
    _sql("INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at) "
         "VALUES (%(p)s, 'likes_waiting_push', 'older', NOW() - interval '6 days')", p=recent['id'])
    _run(ap.queue_likes_waiting, _at(16))
    assert _to(sent, recent) == []


def test_nothing_while_off_or_resting(liked, sent, monkeypatch):
    m, _ = liked()
    monkeypatch.delenv('AHAVAH_PUSH_LIKES_WAITING_ENABLED')
    assert _run(ap.queue_likes_waiting, _at(15)) == 0
    monkeypatch.setenv('AHAVAH_PUSH_LIKES_WAITING_ENABLED', '1')
    monkeypatch.setattr(ap, 'resting', lambda now: True)
    assert _run(ap.queue_likes_waiting, _at(15)) == 0
    assert _to(sent, m) == []


# ---------------------------------------------------------------------------
# New near you
# ---------------------------------------------------------------------------

@pytest.fixture
def newcomer(make_person, add_photo):
    def _make(name, *, gender='Man', country=COUNTRY, days_ago=2, photo=True, roles=None):
        p = make_person(name=name, gender=gender, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
        _sql("UPDATE person SET country = %(c)s, sign_up_time = NOW() - make_interval(days => %(d)s), "
             "roles = COALESCE(%(r)s::text[], roles) WHERE id = %(i)s", c=country, d=days_ago, r=roles, i=p['id'])
        if photo:
            add_photo(p['id'])
        return p
    return _make


@pytest.fixture
def viewer(push_member):
    def _make(name='Leah', *, gender='Woman', tz='UTC', roles=None):
        v = push_member(name, gender=gender, tz=tz)
        _sql("UPDATE person SET country = %(c)s, roles = COALESCE(%(r)s::text[], roles) WHERE id = %(i)s",
             c=COUNTRY, r=roles, i=v['id'])
        return v
    return _make


THURSDAY = 4


def test_new_near_you_counts_who_the_member_could_be_shown(viewer, newcomer, sent):
    v = viewer()
    newcomer('Asher')
    newcomer('NoPhoto', photo=False)
    newcomer('Dinah', gender='Woman')
    newcomer('Abroad', country='QY')
    newcomer('LongAgo', days_ago=10)
    newcomer('Tester', roles=['tester'])
    newcomer('Moderator', roles=['mod'])
    now = _at(15, THURSDAY)
    _run(ap.queue_newcomers, now)
    _run(ap.queue_newcomers, now + timedelta(hours=1))
    pushes = _to(sent, v)
    assert len(pushes) == 1
    p = pushes[0]
    assert (p['title'], p['body']) == ('New on Ahavah near you', f'1 new member joined in {COUNTRY} this week.')
    assert p['url'] == '/discover?src=nnpush' and p['name'] == 'newcomers_push'
    _no_name(p, 'Asher')


def test_new_near_you_pluralises_and_never_sends_a_0(viewer, newcomer, sent):
    v = viewer()
    lonely = viewer('Lonely', gender='Man')            # no woman joined
    newcomer('Gad')
    newcomer('Levi')
    _run(ap.queue_newcomers, _at(15, THURSDAY))
    assert _to(sent, v)[0]['body'] == f'2 new members joined in {COUNTRY} this week.'
    assert _to(sent, lonely) == []
    assert ap.newcomers_push(2, 'Barbados')['body'] == '2 new members joined in Barbados this week.'
    assert ap.newcomers_push(1, 'Barbados')['body'] == '1 new member joined in Barbados this week.'
    from service.spotlight.country import display_country
    assert display_country('BB') == 'Barbados'


def test_new_near_you_goes_on_thursday_from_10_in_the_members_zone(viewer, newcomer, sent):
    v = viewer()
    early = viewer('Early', tz='Pacific/Honolulu')
    newcomer('Judah')
    _run(ap.queue_newcomers, _at(15, 3))               # a Wednesday
    assert _to(sent, v) == []
    _run(ap.queue_newcomers, _at(9, THURSDAY))         # 09:00 in UTC
    assert _to(sent, v) == []
    _run(ap.queue_newcomers, _at(15, THURSDAY))        # 05:00 in Honolulu
    assert len(_to(sent, v)) == 1 and _to(sent, early) == []
    _run(ap.queue_newcomers, _at(21, THURSDAY))        # 11:00 in Honolulu
    assert len(_to(sent, early)) == 1


def test_new_near_you_follows_the_news_toggle_and_tester_line(viewer, newcomer, sent):
    off = viewer('Off')
    _pref(off, 'push_announcements', False)
    tester = viewer('TesterViewer', roles=['tester'])
    newcomer('MemberMan')
    _run(ap.queue_newcomers, _at(15, THURSDAY))
    assert _to(sent, off) == []
    assert _to(sent, tester) == []                     # a member newcomer is not news to a tester
    newcomer('TesterMan', roles=['tester'])
    _sql("DELETE FROM push_send_log WHERE campaign = 'newcomers_push' AND person_id = %(p)s", p=tester['id'])
    _run(ap.queue_newcomers, _at(16, THURSDAY))
    assert _to(sent, tester)[0]['body'] == f'1 new member joined in {COUNTRY} this week.'


# ---------------------------------------------------------------------------
# The Us game with a match
# ---------------------------------------------------------------------------

@pytest.fixture
def match(push_member):
    def _make(a=None, b=None, *, days_ago=3):
        a = a or push_member(f'Anna{uuid4().hex[:4]}', gender='Woman')
        b = b or push_member(f'Eli{uuid4().hex[:4]}', gender='Man')
        with api_tx() as tx:
            mid = tx.execute(
                """INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
                   VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int),
                           NOW() - make_interval(days => %(d)s))
                   RETURNING match_id::text""", dict(a=a['id'], b=b['id'], d=days_ago)).fetchone()['match_id']
        return a, b, mid
    return _make


def test_both_sides_of_a_match_hear_once_and_the_tap_opens_the_chat(match, sent):
    a, b, mid = match()
    now = _at(15)
    _run(ap.queue_us_game, now)
    _run(ap.queue_us_game, now + timedelta(hours=1))
    pa, pb = _to(sent, a), _to(sent, b)
    assert len(pa) == 1 and len(pb) == 1
    assert pa[0]['url'] == f"/chat/{b['uuid']}?src=uspush" and pb[0]['url'] == f"/chat/{a['uuid']}?src=uspush"
    assert (pa[0]['title'], pa[0]['body']) == ('Try the Us game with your match',
                                               'Answer the same questions and see where you agree.')
    assert _logged(a, ap.US_GAME) == [mid]


def test_no_us_game_push_for_a_young_match_or_a_pair_that_played(match, sent, push_member):
    young_a, young_b, _ = match(days_ago=1)
    a, b, _ = match()
    with api_tx() as tx:
        tx.execute("""INSERT INTO tool_session (kind, mode, source, owner_person_id, chat_person_id)
                      VALUES ('checklist', 'couple', 'tool:checklist', %(a)s, %(b)s)""", dict(a=a['id'], b=b['id']))
    c, d, _ = match()
    with api_tx() as tx:
        s = tx.execute("""INSERT INTO tool_session (kind, mode, source, owner_person_id, deleted_at)
                          VALUES ('game', 'us', 'tool:game-us', %(o)s, NOW()) RETURNING id""",
                       dict(o=d['id'])).fetchone()
        tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, person_id)
                      VALUES (%(s)s, 'guest', %(h)s, %(p)s)""", dict(s=s['id'], h=uuid4().hex, p=c['id']))
    _run(ap.queue_us_game, _at(15))
    for p in (young_a, young_b, a, b, c, d):
        assert _to(sent, p) == []


def test_the_us_game_follows_the_matches_toggle_the_tester_line_and_7_days(match, sent, push_member):
    a, b, _ = match()
    _pref(a, 'push_matches', False)
    t1, t2, _ = match()
    _sql("UPDATE person SET roles = ARRAY['tester']::text[] WHERE id = %(i)s", i=t2['id'])
    w = push_member('Busy', gender='Woman')
    match(w)
    match(w)
    _run(ap.queue_us_game, _at(15))
    assert _to(sent, a) == [] and len(_to(sent, b)) == 1
    assert _to(sent, t1) == [] and _to(sent, t2) == []
    assert len(_to(sent, w)) == 1
    _run(ap.queue_us_game, _at(16))
    assert len(_to(sent, w)) == 1                       # 1 in 7 days, whatever the matches


def test_the_us_game_waits_for_together_and_its_switch(match, sent, monkeypatch):
    a, b, _ = match()
    monkeypatch.delenv('AHAVAH_TOGETHER_LIVE_ENABLED')
    _run(ap.queue_us_game, _at(15))
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    monkeypatch.delenv('AHAVAH_PUSH_US_GAME_ENABLED')
    _run(ap.queue_us_game, _at(15))
    assert _to(sent, a) == [] and _to(sent, b) == []


# ---------------------------------------------------------------------------
# Dry runs, tests, the Growth rows and the cron
# ---------------------------------------------------------------------------

def test_a_dry_run_writes_nothing_and_runs_inside_no_send(match, sent, monkeypatch):
    from service.notifications import _send_to_user_blocking
    from smtp import guard
    a, b, _ = match()
    monkeypatch.delenv('AHAVAH_PUSH_US_GAME_ENABLED')       # works while off
    seen = {}

    def probe():
        seen['no_send'] = guard.in_no_send()
        with pytest.raises(guard.SendDuringDryRun):
            _send_to_user_blocking(a['id'], ap.sample(ap.US_GAME), kind='us_game_push')

    monkeypatch.setattr(ap, '_dry_run_probe', probe)
    res = ap.dry_run(ap.US_GAME, _at(15))
    assert seen['no_send'] and res['switch_on'] is False and res['due'] >= 2
    assert sent == [] and _logged(a, ap.US_GAME) == []


def _bearer(person_id):
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=person_id)).fetchone()['email']
        tx.execute("""INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
                      VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
                   dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id))
    return {'Authorization': f'Bearer {tok}'}


def test_the_admin_routes_rows_dry_run_and_test(client, push_member, monkeypatch):
    import service.notifications as notifications
    admin = push_member('AutoAdmin')
    _sql("UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(i)s", i=admin['id'])
    h = _bearer(admin['id'])
    got = []
    monkeypatch.setattr(notifications, 'PUSH_ENABLED', True)
    monkeypatch.setattr(notifications, '_send_to_user_blocking',
                        lambda person_id, payload, kind=None: got.append((person_id, kind, payload)) or 1)
    monkeypatch.delenv('AHAVAH_PUSH_NEWCOMERS_ENABLED')

    rows = client.get('/admin/growth/push/auto', headers=h).get_json()['rows']
    assert [r['name'] for r in rows] == list(ap.NAMES)
    assert {r['name']: r['enabled'] for r in rows}['newcomers_push'] is False
    assert set(rows[0]) == {'name', 'label', 'switch', 'enabled', 'sent_7d', 'tapped_7d'}
    push_card = client.get('/admin/growth/push', headers=h).get_json()
    assert [r['name'] for r in push_card['auto_pushes']] == list(ap.NAMES)

    r = client.post('/admin/growth/push/auto/newcomers_push/dry-run', headers=h)
    assert r.status_code == 200 and r.get_json()['dry_run'] is True
    assert client.post('/admin/growth/push/auto/nope/dry-run', headers=h).status_code == 404

    r = client.post('/admin/growth/push/auto/newcomers_push/test', headers=h)
    assert r.get_json() == dict(delivered=True, reason=None, name='newcomers_push')
    assert got[-1][0] == admin['id'] and got[-1][1] == 'newcomers_push_test'
    with api_tx('read committed') as tx:
        audit = tx.execute("""SELECT metadata FROM admin_audit_log WHERE action = 'push_auto_test'
                               AND actor_uuid = %(u)s""", dict(u=admin['uuid'])).fetchall()
    assert audit and audit[-1]['metadata']['name'] == 'newcomers_push'


def test_the_return_mail_cron_runs_the_3_jobs():
    from service.cron import returnmail
    names = [n for n, _ in returnmail.JOBS]
    assert {'push_likes_waiting', 'push_newcomers', 'push_us_game'} <= set(names)



def test_a_job_sends_at_most_its_run_cap_a_tick(match, sent, monkeypatch):
    match()
    match()
    monkeypatch.setattr(ap, 'RUN_CAP', 1)
    assert _run(ap.queue_us_game, _at(15)) == 1
    assert len(sent) == 1


def test_a_push_no_device_took_is_retried_once_a_period(match, monkeypatch):
    a, b, mid = match()
    tries = []
    monkeypatch.setattr(ap, '_push', lambda person_id, push, name: tries.append(person_id) and 0)
    monkeypatch.setattr(ap, 'PUSH_READY', lambda: True)
    for hour in (13, 14, 15, 16):
        _run(ap.queue_us_game, _at(hour))
    assert tries.count(a['id']) == 2 and tries.count(b['id']) == 2
    assert _logged(a, ap.US_GAME) == [] and _logged(a, ap.failed(ap.US_GAME)) == [mid]
