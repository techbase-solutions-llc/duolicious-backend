"""Inactive profiles stay visible (TEC-1607): the one-off that brings back
the members the dormancy cron hid."""
from database import api_tx
from scripts.reactivate_dormant import reactivate_dormant


def _deactivate(pid, deleting=False):
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = FALSE,
                      deletion_requested_at = CASE WHEN %(d)s THEN NOW() ELSE NULL END
                WHERE id = %(i)s""", dict(i=pid, d=deleting))


def _activated(pid) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute("SELECT activated FROM person WHERE id = %(i)s",
                          dict(i=pid)).fetchone()['activated']


def test_the_dormant_come_back_and_the_deleting_do_not(make_person):
    dormant = make_person(name='Dormant')
    deleting = make_person(name='Deleting')
    _deactivate(dormant['id'])
    _deactivate(deleting['id'], deleting=True)
    with api_tx() as tx:
        ids = {r['person_id'] for r in reactivate_dormant(tx)}
    assert dormant['id'] in ids and deleting['id'] not in ids
    assert _activated(dormant['id']) is True
    assert _activated(deleting['id']) is False


def test_a_dry_run_lists_without_changing(make_person):
    p = make_person(name='Listed')
    _deactivate(p['id'])
    with api_tx() as tx:
        ids = {r['person_id'] for r in reactivate_dormant(tx, dry_run=True)}
    assert p['id'] in ids and _activated(p['id']) is False


def test_a_second_run_changes_nothing(make_person):
    p = make_person(name='Twice')
    _deactivate(p['id'])
    with api_tx() as tx:
        first = {r['person_id'] for r in reactivate_dormant(tx)}
    with api_tx() as tx:
        second = {r['person_id'] for r in reactivate_dormant(tx)}
    assert p['id'] in first and p['id'] not in second
