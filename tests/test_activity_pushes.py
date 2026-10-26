"""The 3 member pushes of the in-app plan's release 4 (TEC-1845): a reminder
of a gathering the member is going to, new guests for a gathering the
member hosts (at most once a day) and "your match finished the game".

Each needs its own switch (off by default) and its feature's, the member's
toggle (on by default), a push subscription and a member who is not staff;
none goes in quiet hours, in a rest period or past the known calendar. The
Settings API shows and changes a toggle only while its push is on."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.campaigns import held
from service.notifications import activity_pushes as ap

pytestmark = pytest.mark.usefixtures('events_schema', 'together_schema', 'release_4_schema', 'events_live',
                                     'together_live', 'pushes_on')

UTC = timezone.utc
_SWITCHES = ('AHAVAH_PUSH_GATHERING_REMINDER_ENABLED', 'AHAVAH_PUSH_NEW_GUESTS_ENABLED',
             'AHAVAH_PUSH_MATCH_PLAYED_ENABLED')


@pytest.fixture
def pushes_on(monkeypatch):
    for env in _SWITCHES:
        monkeypatch.setenv(env, '1')


@pytest.fixture
def sent(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(ap, '_push', lambda person_id, push, kind: out.append(
        dict(push, person_id=person_id, kind=kind)) or 1)
    monkeypatch.setattr(ap, 'PUSH_READY', lambda: True)
    return out


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


# ---------------------------------------------------------------------------
# A reminder of a gathering the member is going to
# ---------------------------------------------------------------------------

def _afternoon(days_ahead: int = 2) -> datetime:
    """15:00 UTC a few days out: the day before a gathering at the same time
    the next day, inside the reminder's hours and outside quiet hours for a
    member in UTC."""
    day = (datetime.now(UTC) + timedelta(days=days_ahead)).date()
    return datetime.combine(day, time(15, 0), UTC)


@pytest.fixture
def going(push_member, published, confirmed_guest):
    def _make(name='Miriam', **member):
        now = _afternoon()
        m = push_member(name, **member)
        slug = published(starts_at=now + timedelta(days=1), tz='UTC', title='Sabbath fellowship lunch')
        rsvp = confirmed_guest(slug, person_id=m['id'])
        return m, rsvp, now
    return _make


def test_the_member_going_is_reminded_once_the_day_before(going, sent):
    m, rsvp, now = going()
    assert _run(ap.queue_gathering_reminders, now) == 1
    (p,) = _to(sent, m)
    assert (p['title'], p['body']) == ('Your gathering is tomorrow',
                                       'Sabbath fellowship lunch is tomorrow. The time and place are in Ahavah.')
    assert (p['url'], p['kind']) == (f"/profile/gatherings/{rsvp['id']}", 'gathering_reminder')
    _run(ap.queue_gathering_reminders, now + timedelta(hours=1))
    assert len(_to(sent, m)) == 1


def test_no_reminder_two_days_before_or_on_the_day(going, sent):
    m, _, now = going()
    _run(ap.queue_gathering_reminders, now - timedelta(days=1))
    _run(ap.queue_gathering_reminders, now + timedelta(days=1, hours=-14))
    assert _to(sent, m) == []


@pytest.mark.parametrize('env', [*_SWITCHES[:1], 'AHAVAH_EVENTS_LIVE_ENABLED'])
def test_no_reminder_while_its_switch_or_gatherings_are_off(going, sent, monkeypatch, env):
    m, _, now = going()
    monkeypatch.delenv(env)
    assert _run(ap.queue_gathering_reminders, now) == 0 and _to(sent, m) == []


def test_no_reminder_when_the_member_turned_it_off(going, sent):
    m, _, now = going()
    _pref(m, 'push_gathering_reminder', False)
    _run(ap.queue_gathering_reminders, now)
    assert _to(sent, m) == []


def test_no_reminder_in_quiet_hours(going, sent):
    m, _, now = going(tz='Asia/Tokyo')  # 15:00 UTC is midnight in Tokyo
    _run(ap.queue_gathering_reminders, now)
    assert _to(sent, m) == []


@pytest.mark.real_calendar
def test_no_reminder_in_a_rest_period_or_past_the_known_calendar(going, sent, monkeypatch):
    m, _, now = going()
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', now.date() + timedelta(days=30))
    monkeypatch.setattr(rd, 'REST_DAYS', (now.date(),))
    _run(ap.queue_gathering_reminders, now)
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', now.date() - timedelta(days=1))
    _run(ap.queue_gathering_reminders, now)
    assert _to(sent, m) == []
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', now.date() + timedelta(days=30))
    _run(ap.queue_gathering_reminders, now)
    assert len(_to(sent, m)) == 1


def test_never_to_staff_or_without_a_subscription(going, sent):
    staff, _, now = going('Staff')
    _sql("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(p)s", p=staff['id'])
    unsubscribed, _, _ = going('NoPush', push=False)
    _run(ap.queue_gathering_reminders, now)
    assert _to(sent, staff) == [] and _to(sent, unsubscribed) == []


def test_a_push_that_reaches_no_device_is_tried_again(going, monkeypatch):
    m, _, now = going()
    monkeypatch.setattr(ap, 'PUSH_READY', lambda: True)
    monkeypatch.setattr(ap, '_push', lambda *a: 0)
    _run(ap.queue_gathering_reminders, now)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = 'gathering_reminder'",
                          dict(p=m['id'])).fetchone() is None


# ---------------------------------------------------------------------------
# New guests for a gathering the member hosts
# ---------------------------------------------------------------------------

@pytest.fixture
def host(push_member, published, monkeypatch):
    """A member who hosts (an organiser with their address) a published
    gathering; quiet hours are left out here and tested above."""
    monkeypatch.setattr(ap, 'quiet', lambda local: False)
    made: list[int] = []

    def _make(name='Ruth', title='Marriage preparation evening'):
        m = push_member(name)
        with api_tx() as tx:
            email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=m['id'])).fetchone()['email']
            oid = tx.execute(
                """INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at)
                   VALUES ('Grace Fellowship', 'fellowship_leader', %(e)s, %(e)s, NOW(), NOW()) RETURNING id""",
                dict(e=email)).fetchone()['id']
        made.append(oid)
        slug = published(dict(id=oid), title=title)
        return m, oid, slug

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM organiser WHERE id = ANY(%(i)s)', dict(i=made))


def test_new_guests_are_counted_into_one_push_a_day(host, published, confirmed_guest, sent):
    m, oid, slug = host()
    confirmed_guest(slug, party_size=2)
    confirmed_guest(slug)
    now = datetime.now(UTC)
    assert _run(ap.queue_new_guests, now) == 1
    (p,) = _to(sent, m)
    assert (p['title'], p['body'], p['url'], p['kind']) == (
        'New guests', '3 new guests are going to Marriage preparation evening.', '/host/gatherings', 'new_guests')
    confirmed_guest(slug)
    _run(ap.queue_new_guests, now + timedelta(minutes=5))
    assert len(_to(sent, m)) == 1, 'at most once a day'


def test_several_gatherings_are_one_push(host, published, confirmed_guest, sent):
    m, oid, slug = host()
    other = published(dict(id=oid), title='Sabbath fellowship lunch')
    confirmed_guest(slug)
    confirmed_guest(other)
    _run(ap.queue_new_guests, datetime.now(UTC))
    (p,) = _to(sent, m)
    assert p['body'] == '2 new guests are going to your gatherings.'


def test_one_guest_reads_in_the_singular():
    assert ap.new_guests_push(1, ['Lunch'])['body'] == '1 new guest is going to Lunch.'


def test_guests_already_told_are_not_counted_again(host, confirmed_guest, sent):
    m, oid, slug = host()
    confirmed_guest(slug)
    _sql("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
            VALUES (%(p)s, 'new_guests', '2000-01-01', NOW() + INTERVAL '1 minute')""", p=m['id'])
    _run(ap.queue_new_guests, datetime.now(UTC))
    assert _to(sent, m) == []


@pytest.mark.parametrize('env', [_SWITCHES[1], 'AHAVAH_EVENTS_HOSTING_ENABLED'])
def test_no_new_guests_push_while_its_switch_or_hosting_is_off(host, confirmed_guest, sent, monkeypatch, env):
    m, _, slug = host()
    confirmed_guest(slug)
    monkeypatch.delenv(env)
    _run(ap.queue_new_guests, datetime.now(UTC))
    assert _to(sent, m) == []


def test_no_new_guests_push_when_turned_off_or_for_a_gathering_that_ended(host, published, confirmed_guest, sent):
    m, oid, slug = host()
    confirmed_guest(slug)
    _pref(m, 'push_new_guests', False)
    _run(ap.queue_new_guests, datetime.now(UTC))
    assert _to(sent, m) == []
    m2, oid2, _ = host('Naomi')
    ended = published(dict(id=oid2), starts_at=datetime.now(UTC) - timedelta(days=2))
    confirmed_guest(ended)
    _run(ap.queue_new_guests, datetime.now(UTC))
    assert _to(sent, m2) == []


@pytest.mark.real_calendar
def test_no_new_guests_push_in_a_rest_period(host, confirmed_guest, sent, monkeypatch):
    m, _, slug = host()
    confirmed_guest(slug)
    now = datetime.now(UTC)
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', now.date() + timedelta(days=30))
    monkeypatch.setattr(rd, 'REST_DAYS', (now.astimezone(rd.BARBADOS).date(),
                                          now.astimezone(rd.BARBADOS).date() + timedelta(days=1)))
    _run(ap.queue_new_guests, now)
    assert _to(sent, m) == []


# ---------------------------------------------------------------------------
# Your match finished the game
# ---------------------------------------------------------------------------

@pytest.fixture
def us_game(push_member, monkeypatch):
    """us_game(matched=True) -> (first, second, session uuid): two members
    played Us; the first finished an hour before the second."""
    monkeypatch.setattr(ap, 'quiet', lambda local: False)

    def _make(matched: bool = True, first_is_owner: bool = True):
        a = push_member('Hannah', gender='Woman')
        b = push_member('Daniel', gender='Man')
        owner, guest = (a, b) if first_is_owner else (b, a)
        with api_tx() as tx:
            if matched:
                tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                           'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                           dict(a=a['id'], b=b['id']))
            s = tx.execute(
                """INSERT INTO tool_session (kind, mode, source, owner_person_id, claimed_at, completed_at)
                   VALUES ('game', 'us', 'tool:game-us', %(o)s, NOW(), NOW()) RETURNING id, uuid::text""",
                dict(o=owner['id'])).fetchone()
            for seat, who in (('owner', owner), ('guest', guest)):
                finished = "NOW() - INTERVAL '1 hour'" if who is a else 'NOW()'
                tx.execute(f"""INSERT INTO tool_player (session_id, seat, token_hash, person_id, finished_at)
                               VALUES (%(s)s, %(seat)s, %(h)s, %(p)s, {finished})""",
                           dict(s=s['id'], seat=seat, h=uuid4().hex, p=None if seat == 'owner' else who['id']))
        return a, b, s['uuid']

    return _make


@pytest.mark.parametrize('first_is_owner', [True, False])
def test_the_member_who_was_waiting_hears_once(us_game, sent, first_is_owner):
    waiting, finished, sid = us_game(first_is_owner=first_is_owner)
    assert _run(ap.queue_match_played, datetime.now(UTC)) >= 1
    (p,) = _to(sent, waiting)
    assert (p['title'], p['body']) == ('Your result is ready',
                                       'Daniel has finished the game. See how you answered together.')
    assert (p['url'], p['kind']) == (f'/together/game?session={sid}', 'match_played')
    assert _to(sent, finished) == []
    _run(ap.queue_match_played, datetime.now(UTC))
    assert len(_to(sent, waiting)) == 1


def test_only_between_two_matched_members(us_game, sent):
    a, b, _ = us_game(matched=False)
    _run(ap.queue_match_played, datetime.now(UTC))
    assert _to(sent, a) == [] and _to(sent, b) == []


@pytest.mark.parametrize('env', [_SWITCHES[2], 'AHAVAH_TOGETHER_LIVE_ENABLED'])
def test_no_match_played_push_while_its_switch_or_together_is_off(us_game, sent, monkeypatch, env):
    a, _, _ = us_game()
    monkeypatch.delenv(env)
    _run(ap.queue_match_played, datetime.now(UTC))
    assert _to(sent, a) == []


def test_no_match_played_push_when_turned_off(us_game, sent):
    a, _, _ = us_game()
    _pref(a, 'push_match_played', False)
    _run(ap.queue_match_played, datetime.now(UTC))
    assert _to(sent, a) == []


@pytest.mark.real_calendar
def test_a_rest_period_holds_the_push_and_it_goes_after(us_game, sent, monkeypatch):
    a, _, _ = us_game()
    now = datetime.now(UTC)
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', now.date() + timedelta(days=30))
    monkeypatch.setattr(rd, 'REST_DAYS', (now.astimezone(rd.BARBADOS).date(),
                                          now.astimezone(rd.BARBADOS).date() + timedelta(days=1)))
    _run(ap.queue_match_played, now)
    assert _to(sent, a) == []
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    _run(ap.queue_match_played, now + timedelta(days=1, hours=8))
    assert len(_to(sent, a)) == 1


# ---------------------------------------------------------------------------
# Settings > Notifications
# ---------------------------------------------------------------------------

_TOGGLES = ('push_gathering_reminder', 'push_new_guests', 'push_match_played')


def test_each_toggle_shows_only_while_its_push_is_on(client, make_person, sign_in, monkeypatch):
    h = sign_in(make_person(name='Settings'))
    prefs = client.get('/notifications/preferences', headers=h).get_json()
    assert {k: prefs[k] for k in _TOGGLES} == dict.fromkeys(_TOGGLES, True)
    monkeypatch.delenv('AHAVAH_PUSH_NEW_GUESTS_ENABLED')
    monkeypatch.delenv('AHAVAH_TOGETHER_LIVE_ENABLED')
    prefs = client.get('/notifications/preferences', headers=h).get_json()
    assert 'push_new_guests' not in prefs and 'push_match_played' not in prefs
    assert prefs['push_gathering_reminder'] is True and prefs['push_questions'] is True


def test_a_toggle_changes_while_on_and_a_dark_one_is_ignored(client, make_person, sign_in, monkeypatch):
    p = make_person(name='Toggler')
    h = sign_in(p)
    r = client.patch('/notifications/preferences', json=dict(push_gathering_reminder=False), headers=h)
    assert r.status_code == 204
    assert client.get('/notifications/preferences', headers=h).get_json()['push_gathering_reminder'] is False
    monkeypatch.delenv('AHAVAH_PUSH_MATCH_PLAYED_ENABLED')
    r = client.patch('/notifications/preferences', json=dict(push_match_played=False, push_questions=True),
                     headers=h)
    assert r.status_code == 204
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT push_match_played FROM notification_preference WHERE person_id = %(p)s',
                         dict(p=p['id'])).fetchone()
    assert row['push_match_played'] is True


def test_the_proof_script_carries_the_three_pushes():
    from scripts import send_proofs as sp
    kinds = [p['kind'] for p in sp.plan()[1]]
    assert {'gathering_reminder', 'new_guests', 'match_played'} <= set(kinds)
    for p in ap.proof_pushes():
        for text in (p['title'], p['body']):
            assert '!' not in text and '—' not in text and '–' not in text
            assert text[0].isupper() or text[0].isdigit()
