"""A bio save that meets a concurrent write to the same member is retried
(15 Oct 2026). On 14 Oct one member's bio edits failed 31 times in about 5
minutes with SerializationFailure: api_tx is REPEATABLE READ, the web saves
the bio as it is typed, and the member's own presence and profile writes
touch the same row. The other profile fields already retried (2026-07-22);
the bio path did not."""
from contextlib import contextmanager

import psycopg

import service.person as person
from database import api_tx


def test_a_bio_save_that_meets_a_concurrent_write_is_retried(make_person, monkeypatch):
    p = make_person(name='BioRetry')
    real = person.api_tx
    calls = {'n': 0}

    @contextmanager
    def conflicting_once(*a, **k):
        calls['n'] += 1
        with real(*a, **k) as tx:
            yield tx
            if calls['n'] == 1:
                raise psycopg.errors.SerializationFailure(
                    'could not serialize access due to concurrent update')

    monkeypatch.setattr(person, 'api_tx', conflicting_once)
    person._patch_profile_info_about(p['id'], 'A bio written while the app was busy')

    with api_tx() as tx:
        about = tx.execute("SELECT about FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['about']
    assert about == 'A bio written while the app was busy'
    assert calls['n'] == 2
