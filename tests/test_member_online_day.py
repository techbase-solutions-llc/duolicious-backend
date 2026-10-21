"""The days a member is online (TEC-1897): written with each presence bump
so "came back within 7 days of an email" can be answered. Presence itself
must move exactly as before, or autodeactivate2 logs active members out."""
from __future__ import annotations

from commonsql import Q_UPDATE_LAST
from database import api_tx
from service.person import bump_presence


def _set_last_online(person, interval: str) -> None:
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET last_online_time = NOW() - INTERVAL '{interval}' WHERE id = %(i)s",
                   dict(i=person['id']))


def _state(person) -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(
            """SELECT p.last_online_time > NOW() - INTERVAL '1 minute' AS fresh,
                      d.first_at, d.last_at
                 FROM person p
                 LEFT JOIN member_online_day d
                   ON d.person_id = p.id AND d.day = (NOW() AT TIME ZONE 'America/Barbados')::date
                WHERE p.id = %(i)s""", dict(i=person['id'])).fetchone())


def test_presence_still_moves_last_online(make_person):
    p = make_person(name='PresChat')
    _set_last_online(p, '2 days')
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    s = _state(p)
    assert s['fresh'] is True and s['first_at'] is not None and s['first_at'] == s['last_at']


def test_a_second_bump_keeps_the_first_time_of_the_day(make_person):
    p = make_person(name='PresTwice')
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    first = _state(p)['first_at']
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    s = _state(p)
    assert s['first_at'] == first and s['last_at'] >= first


def test_the_rest_bump_records_the_day_too(make_person):
    p = make_person(name='PresRest')
    _set_last_online(p, '1 hour')
    bump_presence(p['id'])
    s = _state(p)
    assert s['fresh'] is True and s['first_at'] is not None


def test_a_bump_inside_ten_minutes_writes_nothing(make_person):
    p = make_person(name='PresQuiet')
    _set_last_online(p, '2 minutes')
    bump_presence(p['id'])
    assert _state(p)['first_at'] is None
