"""The weekly drop day, the card's question and the catch-up run (TEC-1845).

Owner decision 1 (16 Oct): the question drops on the first free day of each
Sunday-to-Saturday week by the lunar rule, never a fixed Sunday. A free day
is not a rest day and not the eve of one (a rest period starts 17:00
Barbados the evening before). Nothing is decided past KNOWN_THROUGH. The
card shows the latest approved drop for up to 14 days. The catch-up run
offers every active question the member has not answered, leaving out this
week's (decision 10), and "Not now" holds on every device.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.questions.schedule import barbados_today, current_drop, drop_day, week_start

pytestmark = pytest.mark.usefixtures('questions_schema', 'questions_live')

SUN = date(2027, 1, 3)  # a Sunday


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2027, 12, 31))

    def rest(*days):
        monkeypatch.setattr(rd, 'REST_DAYS', tuple(days))
    rest()
    return rest


def test_a_week_runs_sunday_to_saturday():
    assert [week_start(SUN + timedelta(days=i)) for i in range(7)] == [SUN] * 7
    assert week_start(SUN + timedelta(days=7)) == SUN + timedelta(days=7)


def test_with_no_rest_day_the_drop_is_the_sunday(calendar):
    assert drop_day(SUN + timedelta(days=4)) == SUN


def test_a_rest_sunday_and_monday_move_the_drop_to_tuesday(calendar):
    calendar(SUN, SUN + timedelta(days=1))
    assert drop_day(SUN) == SUN + timedelta(days=2)


def test_the_eve_of_a_rest_day_is_not_a_drop_day(calendar):
    calendar(SUN + timedelta(days=1))
    assert drop_day(SUN) == SUN + timedelta(days=2)


def test_a_week_past_the_known_calendar_has_no_drop(calendar, monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', SUN - timedelta(days=1))
    assert drop_day(SUN) is None
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', SUN + timedelta(days=2))
    calendar(SUN, SUN + timedelta(days=1))
    assert drop_day(SUN) is None, 'Tuesday needs Wednesday to be known'


@pytest.mark.real_calendar
def test_the_owners_october_calendar():
    # restdays.py as confirmed on 26 Oct (TEC-1933): eighth month Sabbaths
    # on Sundays to 8 Nov, ninth month Sabbaths on Tuesdays to 8 Dec, known
    # through 8 Dec. A rest Sunday moves the drop to Monday; a Sunday before
    # a Tuesday Sabbath is free. Update this test when the tenth is read.
    assert drop_day(date(2026, 10, 18)) == date(2026, 10, 19)
    assert drop_day(date(2026, 10, 25)) == date(2026, 10, 26)
    assert drop_day(date(2026, 11, 1)) == date(2026, 11, 2)
    assert drop_day(date(2026, 11, 8)) == date(2026, 11, 9)
    assert drop_day(date(2026, 11, 15)) == date(2026, 11, 15)
    assert drop_day(date(2026, 12, 6)) == date(2026, 12, 6)
    assert drop_day(date(2026, 12, 13)) is None


def _at(day: date) -> datetime:
    return datetime.combine(day, time(15, 0), timezone.utc)


def test_the_current_question_is_the_latest_approved_drop(make_question, drops):
    q1, q2, q3 = make_question(), make_question(), make_question()
    drops(SUN, q1['key'])
    drops(SUN + timedelta(days=7), q2['key'])
    drops(SUN + timedelta(days=14), q3['key'], approved=False)
    with api_tx('read committed') as tx:
        got = current_drop(tx, _at(SUN + timedelta(days=16)))
    assert got == dict(live_on=SUN + timedelta(days=7), question=q2)


def test_a_drop_stays_current_for_14_days_and_not_before_it_goes_live(make_question, drops):
    q = make_question()
    drops(SUN, q['key'])
    with api_tx('read committed') as tx:
        assert current_drop(tx, _at(SUN - timedelta(days=1))) is None
        assert current_drop(tx, _at(SUN + timedelta(days=13)))['question'] == q
        assert current_drop(tx, _at(SUN + timedelta(days=14))) is None


def test_a_switched_off_question_is_not_current(make_question, drops):
    q = make_question()
    drops(SUN, q['key'])
    with api_tx() as tx:
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE key = %(k)s', dict(k=q['key']))
        assert current_drop(tx, _at(SUN)) is None


def _member(make_person, sign_in, name):
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def test_the_card_question_comes_with_the_members_answer(client, make_person, sign_in, make_question, drops):
    q = make_question()
    today = barbados_today()
    drops(today, q['key'])
    me = _member(make_person, sign_in, 'CardMe')
    cur = client.get('/questions/current', headers=me['headers']).get_json()['current']
    assert (cur['live_on'], cur['question'], cur['my_choice'], cur['counts']) == (today.isoformat(), q, None, None)
    client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=q['options'][1]['key']))
    cur = client.get('/questions/current', headers=me['headers']).get_json()['current']
    assert cur['my_choice'] == q['options'][1]['key']


def test_catch_up_offers_every_active_question_except_this_weeks(client, make_person, sign_in, make_question, drops):
    week, other = make_question(), make_question()
    drops(barbados_today(), week['key'])
    me = _member(make_person, sign_in, 'CatchUpMe')
    keys = [x['key'] for x in client.get('/questions/catch-up', headers=me['headers']).get_json()['questions']]
    assert other['key'] in keys and 'mountains-or-sea' in keys
    assert week['key'] not in keys and 'pet' not in keys
    client.put(f"/answers/{other['key']}", headers=me['headers'], json=dict(choice_key=other['options'][0]['key']))
    keys = [x['key'] for x in client.get('/questions/catch-up', headers=me['headers']).get_json()['questions']]
    assert other['key'] not in keys


def test_not_now_holds_on_every_device(client, make_person, sign_in):
    p = make_person(name='DeclineMe')
    phone, laptop = sign_in(p), sign_in(p)
    assert client.get('/questions/catch-up', headers=laptop).get_json()['declined'] is False
    assert client.post('/questions/catch-up/decline', headers=phone).status_code == 204
    with api_tx('read committed') as tx:
        first = tx.execute('SELECT question_catchup_declined_at AS d FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['d']
    assert client.get('/questions/catch-up', headers=laptop).get_json()['declined'] is True
    client.post('/questions/catch-up/decline', headers=laptop)
    with api_tx('read committed') as tx:
        again = tx.execute('SELECT question_catchup_declined_at AS d FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['d']
    assert again == first
