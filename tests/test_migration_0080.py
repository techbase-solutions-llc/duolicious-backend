"""Migrations 0080 to 0082 (TEC-1845, in-app entry plan release 3). Each is
idempotent, as the deploy may run it more than once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('release3_schema')
MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


@pytest.mark.parametrize('name', ['0080_organiser_member.sql', '0081_event_share_tags.sql',
                                  '0082_recommendation_landing.sql'])
def test_runs_twice(name):
    sql = (MIGRATIONS / name).read_text(encoding='utf-8')
    with api_tx() as tx:
        tx.execute(sql)
        tx.execute(sql)


def test_an_organiser_keeps_the_member_who_made_it_until_the_member_goes(organiser, make_person):
    o = organiser()
    member = make_person(name='Samuel')
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET member_person_id = %(p)s WHERE id = %(o)s',
                   dict(p=member['id'], o=o['id']))
    with api_tx() as tx:
        tx.execute('DELETE FROM person WHERE id = %(p)s', dict(p=member['id']))
    with api_tx() as tx:
        row = tx.execute('SELECT member_person_id FROM organiser WHERE id = %(o)s', dict(o=o['id'])).fetchone()
    assert row is not None and row['member_person_id'] is None


def test_a_view_share_tag_is_one_of_four(published):
    slug = published()
    with api_tx() as tx:
        eid = tx.execute('SELECT id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()['id']
        for tag in ('host', 'guest', 'app', 'feed'):
            tx.execute("INSERT INTO event_view_share_day (event_id, day, share_tag, views) "
                       "VALUES (%(e)s, CURRENT_DATE, %(t)s, 1)", dict(e=eid, t=tag))
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO event_view_share_day (event_id, day, share_tag, views) "
                       "VALUES (%(e)s, CURRENT_DATE, 'email', 1)", dict(e=eid))
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO event_rsvp (event_id, name, email, normalized_email, party_size, "
                       "token_hash, confirm_by, source, share_tag) VALUES (%(e)s, 'X', 'x@ahavah-test.invalid', "
                       "'x@ahavah-test.invalid', 1, 'h', NOW(), 'event:x', 'email')", dict(e=eid))


def test_a_landing_token_names_one_recommendation():
    with api_tx() as tx:
        tx.execute("SELECT landing_token_hash FROM recommendation LIMIT 0")
