"""The alert notices (TEC-1845): daily for members, weekly for visitors, a
count and never who, one email for both reasons, and new fits first.

Everyone a test counts is 62 years old, an age the suite's other people
never have (make_person is born 1990), so the shared database's other rows
never enter a count.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service.matchmaker import notices

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

AGE = 62


def _born() -> date:
    today = date.today()
    return date(today.year - AGE, 1, 1) if (today.month, today.day) > (1, 1) else date(today.year - AGE - 1, 1, 1)


def _at(days_ahead: int, hour: int = 12) -> datetime:
    d = datetime.now(timezone.utc).date() + timedelta(days=days_ahead)
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.utc)


def _next(weekday: int, hour: int = 12) -> datetime:
    """The first such weekday at least 2 days ahead."""
    for ahead in range(2, 9):
        at = _at(ahead, hour)
        if at.weekday() == weekday:
            return at
    raise AssertionError


def _run(fn, now):
    from service.campaigns import held
    with api_tx() as tx:
        n = fn(tx, now)
    held.run_after_commit()
    return n


@pytest.fixture
def pushes(monkeypatch):
    from service.matchmaker import mail
    sent: list[dict] = []
    monkeypatch.setattr(mail, '_send_push', lambda pid, push, kind: sent.append(dict(push, person_id=pid)))
    return sent


@pytest.fixture
def owner(make_person, sign_in):
    """owner(push=False, email=True, **criteria) -> dict: a mailable woman
    looking for men, with an alert for ages 61 to 63 counting from now."""
    def _make(*, push: bool = False, email: bool = True, subscribed: bool = False, **criteria) -> dict:
        p = make_person(name='Miriam Levi', gender='Woman',
                        email=f'miriam-{uuid4().hex[:8]}@ahavah-test.invalid')
        h = sign_in(p)
        with api_tx() as tx:
            tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=p['id']))
            tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                       "SELECT %(i)s, id FROM gender WHERE name = 'Man'", dict(i=p['id']))
            if subscribed:
                tx.execute("INSERT INTO push_subscription (person_id, endpoint, p256dh, auth) "
                           "VALUES (%(i)s, %(e)s, 'k', 'a')", dict(i=p['id'], e=f'https://push.test/{uuid4()}'))
        from service.matchmaker.alerts import save_member_alert
        with api_tx() as tx:
            save_member_alert(tx, p['id'], dict(dict(age_min=AGE - 1, age_max=AGE + 1), **criteria),
                              notify_push=push, notify_email=email)
            tx.execute("UPDATE match_alert SET counted_since = NOW() - interval '1 minute' "
                       "WHERE person_id = %(i)s", dict(i=p['id']))
        return dict(p, headers=h)
    return _make


@pytest.fixture
def newcomer(make_person, add_photo):
    def _make(name: str = 'Daniel', gender: str = 'Man', *, photo: bool = True, country: str = 'US',
              extra: dict | None = None) -> dict:
        import json
        p = make_person(name=name, gender=gender)
        with api_tx() as tx:
            tx.execute("""UPDATE person SET activated = TRUE, date_of_birth = %(b)s, country = %(c)s,
                                 ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || %(x)s::jsonb
                           WHERE id = %(i)s""",
                       dict(b=_born(), c=country, x=json.dumps(extra or {}), i=p['id']))
        if photo:
            add_photo(p['id'])
        return p
    return _make


def _alert_rows(person_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'mm_alert' AND person_id = %(p)s ORDER BY id",
            dict(p=person_id)).fetchall()]


def _notices(person_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT n.* FROM match_alert_notice n JOIN match_alert a ON a.id = n.alert_id
                WHERE a.person_id = %(p)s ORDER BY n.id""", dict(p=person_id)).fetchall()]


def test_a_new_member_who_fits_brings_one_notice_a_day(owner, newcomer):
    me = owner()
    newcomer()
    now = _at(1)
    assert _run(notices.queue_member_notices, now) >= 1
    [row] = _alert_rows(me['id'])
    assert row['payload']['subject'] == '1 new member fits what you are looking for'
    assert 'Daniel' not in row['payload']['html']
    [notice] = _notices(me['id'])
    assert notice['members'] == 1 and notice['audience'] == 'member' and notice['by_email'] is True
    newcomer('Joel')
    _run(notices.queue_member_notices, now + timedelta(hours=3))
    assert len(_alert_rows(me['id'])) == 1


def test_the_next_day_counts_only_who_joined_since(owner, newcomer):
    me = owner()
    first = newcomer()
    _run(notices.queue_member_notices, _at(1))
    # The test's "next day" is now: the window starts where the first one counted.
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET counted_since =
                             (SELECT sign_up_time AT TIME ZONE 'UTC' FROM person WHERE id = %(d)s)
                       WHERE person_id = %(i)s""", dict(i=me['id'], d=first['id']))
    newcomer('Joel')
    newcomer('Josiah')
    _run(notices.queue_member_notices, _at(2))
    rows = _alert_rows(me['id'])
    assert [r['payload']['subject'] for r in rows] == [
        '1 new member fits what you are looking for', '2 new members fit what you are looking for']


def test_nothing_before_12_or_inside_a_rest_period(owner, newcomer, monkeypatch):
    me = owner()
    newcomer()
    _run(notices.queue_member_notices, _at(1, hour=11))
    assert _alert_rows(me['id']) == []
    import service.spotlight.restdays as rd
    monkeypatch.setattr(rd, 'is_rest_period', lambda at: True)
    _run(notices.queue_member_notices, _at(1))
    assert _alert_rows(me['id']) == []
    monkeypatch.setattr(rd, 'is_rest_period', lambda at: False)
    _run(notices.queue_member_notices, _at(1))
    assert len(_alert_rows(me['id'])) == 1 and _notices(me['id'])[0]['members'] == 1


def test_the_count_leaves_out_who_the_deck_leaves_out(owner, newcomer):
    me = owner()
    hidden = newcomer('Hidden')
    held_ = newcomer('Held')
    staff = newcomer('Staff')
    blocked = newcomer('Blocked')
    unmatched = newcomer('Unmatched')
    newcomer('NoPhoto', photo=False)
    newcomer('AWoman', gender='Woman')
    with api_tx() as tx:
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s', dict(i=hidden['id']))
        tx.execute('UPDATE person SET verification_required = TRUE WHERE id = %(i)s', dict(i=held_['id']))
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) VALUES (%(a)s, %(b)s, TRUE)',
                   dict(a=me['id'], b=blocked['id']))
        tx.execute('INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by) '
                   'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int), %(a)s)',
                   dict(a=me['id'], b=unmatched['id']))
    _run(notices.queue_member_notices, _at(1))
    assert _alert_rows(me['id']) == [] and _notices(me['id']) == []
    newcomer('Plain')
    _run(notices.queue_member_notices, _at(1))
    assert _notices(me['id'])[0]['members'] == 1


def test_criteria_narrow_the_count(owner, newcomer):
    me = owner(wants_children='yes')
    newcomer('SaidNo', extra=dict(wantsChildren='no'))
    newcomer('NoAnswer')
    newcomer('SaidYes', extra=dict(wantsChildren='yes'))
    _run(notices.queue_member_notices, _at(1))
    assert _notices(me['id'])[0]['members'] == 2


def test_a_region_carried_from_a_visitor_alert_counts_its_countries(owner, newcomer):
    me = owner(regions=['europe'])
    newcomer('American', country='US')
    newcomer('Briton', country='GB')
    _run(notices.queue_member_notices, _at(1))
    assert _notices(me['id'])[0]['members'] == 1


def test_push_when_it_can_reach_them_else_email(owner, newcomer, pushes):
    reached = owner(push=True, email=False, subscribed=True)
    unreached = owner(push=True, email=False, subscribed=False)
    newcomer()
    _run(notices.queue_member_notices, _at(1))
    assert [p['person_id'] for p in pushes if p['person_id'] in (reached['id'], unreached['id'])] == [reached['id']]
    assert pushes[[p['person_id'] for p in pushes].index(reached['id'])]['body'] == \
        '1 new member fits what you are looking for'
    assert _alert_rows(reached['id']) == [] and len(_alert_rows(unreached['id'])) == 1
    assert _notices(reached['id'])[0]['by_push'] is True and _notices(unreached['id'])[0]['by_email'] is True


def test_the_push_waits_for_its_switch(owner, newcomer, pushes, monkeypatch):
    monkeypatch.delenv('AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED')
    me = owner(push=True, email=False, subscribed=True)
    newcomer()
    _run(notices.queue_member_notices, _at(1))
    assert [p for p in pushes if p['person_id'] == me['id']] == []
    assert len(_alert_rows(me['id'])) == 1


def test_a_paused_alert_hears_nothing(owner, newcomer):
    from service.matchmaker.alerts import pause
    me = owner()
    with api_tx() as tx:
        pause(tx, me['id'])
    newcomer()
    _run(notices.queue_member_notices, _at(1))
    assert _alert_rows(me['id']) == []


def _offline_with_likes(me, make_person, n=2):
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - interval '5 days' WHERE id = %(i)s",
                   dict(i=me['id']))
    for _ in range(n):
        liker = make_person(name='Liker', gender='Man')
        with api_tx() as tx:
            tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=liker['id']))
            tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)',
                       dict(a=liker['id'], b=me['id']))


def test_the_likes_ride_in_the_alert_and_the_likes_email_skips_them(owner, newcomer, make_person, monkeypatch):
    from emails import likes_waiting_weekly as lw
    monkeypatch.setenv('AHAVAH_LIKES_WAITING_ENABLED', '1')
    me = owner()
    _offline_with_likes(me, make_person)
    newcomer()
    thursday = _next(3)
    _run(notices.queue_member_notices, thursday)
    [row] = _alert_rows(me['id'])
    assert '2 people are also waiting for your answer' in row['payload']['html']
    assert 'One email for both, at most once a day.' in row['payload']['html']
    with api_tx() as tx:
        lw.queue_due(tx, thursday)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM email_outbox WHERE campaign = 'likes_waiting' AND person_id = %(p)s",
                          dict(p=me['id'])).fetchone() is None


def test_beside_an_alert_the_likes_email_drops_its_fit_line(owner, make_person, monkeypatch):
    from emails import likes_waiting_weekly as lw
    monkeypatch.setenv('AHAVAH_LIKES_WAITING_ENABLED', '1')
    monkeypatch.setattr(lw, 'count_newcomers_since', lambda tx, pid, since: 3)
    me = owner()
    _offline_with_likes(me, make_person)
    plain = make_person(name='NoAlert', gender='Woman', email=f'noalert-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=plain['id']))
    _offline_with_likes(plain, make_person)
    with api_tx() as tx:
        lw.queue_due(tx, _next(3))
    with api_tx('read committed') as tx:
        rows = {r['person_id']: r['payload']['html'] for r in tx.execute(
            "SELECT person_id, payload FROM email_outbox WHERE campaign = 'likes_waiting' "
            "AND person_id = ANY(%(p)s)", dict(p=[me['id'], plain['id']])).fetchall()}
    assert 'who fit what you are looking for' not in rows[me['id']]
    assert '3 new people who fit what you are looking for' in rows[plain['id']]


@pytest.mark.parametrize('env', ['AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED', 'AHAVAH_MATCHMAKER_LIVE_ENABLED'])
def test_with_the_alert_email_off_the_likes_email_is_as_before(owner, make_person, monkeypatch, env):
    """The alert's email cannot tell her about new fits, so the likes email
    keeps its line (review, 21 Oct)."""
    from emails import likes_waiting_weekly as lw
    monkeypatch.setenv('AHAVAH_LIKES_WAITING_ENABLED', '1')
    monkeypatch.setattr(lw, 'count_newcomers_since', lambda tx, pid, since: 3)
    me = owner()
    _offline_with_likes(me, make_person)
    monkeypatch.delenv(env)
    with api_tx() as tx:
        lw.queue_due(tx, _next(3))
    with api_tx('read committed') as tx:
        [row] = tx.execute("SELECT payload FROM email_outbox WHERE campaign = 'likes_waiting' "
                           "AND person_id = %(p)s", dict(p=me['id'])).fetchall()
    assert '3 new people who fit what you are looking for' in row['payload']['html']


@pytest.fixture
def visitor(make_person):
    """A confirmed visitor alert for a man aged 61 to 63 in North America,
    counting from now."""
    made: list[str] = []

    def _make() -> dict:
        from service.leads import confirm_lead, record_lead
        email = f'visitor-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(email)
        with api_tx() as tx:
            lid = record_lead(tx, email=email, source='alert:visitor')
            confirm_lead(tx, lid, 'link')
            aid = tx.execute(
                """INSERT INTO match_alert (lead_id, first_name, criteria, notify_push, confirmed_at,
                                            counted_since)
                   VALUES (%(l)s, 'Hannah', %(c)s::jsonb, FALSE, NOW(), NOW() - interval '1 minute')
                   RETURNING id""",
                dict(l=lid, c='{"looking_for": "man", "age_min": 61, "age_max": 63, "region": "north-america"}'),
            ).fetchone()['id']
        return dict(lead_id=lid, alert_id=aid, email=email)

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _visitor_rows(lead_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'mm_visitor_alert' AND lead_id = %(l)s",
            dict(l=lead_id)).fetchall()]


def test_a_visitor_hears_once_a_week(visitor, newcomer):
    v = visitor()
    newcomer('American', country='US')
    newcomer('Briton', country='GB')
    thursday = _next(3)
    _run(notices.queue_visitor_notices, thursday - timedelta(days=1))
    assert _visitor_rows(v['lead_id']) == []
    _run(notices.queue_visitor_notices, thursday)
    [row] = _visitor_rows(v['lead_id'])
    assert '1 new member this week.' in row['payload']['html'] and 'Hello Hannah.' in row['payload']['html']
    assert row['payload']['subject'] == 'Someone who fits what you are looking for joined Ahavah'
    newcomer('Another', country='CA')
    _run(notices.queue_visitor_notices, thursday + timedelta(hours=2))
    assert len(_visitor_rows(v['lead_id'])) == 1


def test_a_visitor_who_joined_hears_nothing_as_a_visitor(visitor, newcomer, make_person):
    v = visitor()
    joined = make_person(name='Hannah')
    with api_tx() as tx:
        tx.execute('UPDATE lead SET person_id = %(p)s, converted_at = NOW() WHERE id = %(l)s',
                   dict(p=joined['id'], l=v['lead_id']))
    newcomer()
    _run(notices.queue_visitor_notices, _next(3))
    assert _visitor_rows(v['lead_id']) == []


def test_see_who_joined_puts_the_new_fits_first(client, owner, newcomer):
    me = owner()
    fit = newcomer()
    _run(notices.queue_member_notices, _at(1))
    with api_tx('read committed') as tx:
        assert fit['id'] in notices.new_fit_ids(tx, me['id'])
    r = client.get('/search?n=10&o=0&fits_first=1', headers=me['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()[0]['prospect_uuid'] == fit['uuid']


def test_both_jobs_run_before_the_likes_email():
    from service.cron.returnmail import JOBS
    names = [n for n, _ in JOBS]
    assert names.index('mm_member_alerts') < names.index('likes_waiting')
    assert names.index('mm_visitor_alerts') < names.index('likes_waiting')
