"""Migration 0076 (TEC-1845, docs/superpowers/plans/2026-10-22-events-invite-to-join.md,
Task 3): one invitation to join per address, across all gatherings. The
primary key is the "once"; the gathering may go and the record stays."""
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('join_invite_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations'
       / '0076_lead_join_invite.sql').read_text(encoding='utf-8')


def _address() -> str:
    return f'join-invite-{uuid4().hex[:12]}@ahavah-test.invalid'


@pytest.fixture
def addresses():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM lead_join_invite WHERE normalized_email = ANY(%(a)s)', dict(a=made))


def test_runs_twice():
    with api_tx() as tx:
        tx.execute(SQL)
        tx.execute(SQL)


def test_one_row_per_address(addresses):
    a = _address()
    addresses.append(a)
    with api_tx() as tx:
        tx.execute('INSERT INTO lead_join_invite (normalized_email) VALUES (%(a)s)', dict(a=a))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            tx.execute('INSERT INTO lead_join_invite (normalized_email) VALUES (%(a)s)', dict(a=a))


def test_the_gathering_may_go_and_the_record_stays(published, addresses):
    slug = published()
    a = _address()
    addresses.append(a)
    with api_tx() as tx:
        tx.execute("""INSERT INTO lead_join_invite (normalized_email, event_id)
                      SELECT %(a)s, id FROM event WHERE slug = %(s)s""", dict(a=a, s=slug))
        tx.execute('DELETE FROM event WHERE slug = %(s)s', dict(s=slug))
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM lead_join_invite WHERE normalized_email = %(a)s',
                         dict(a=a)).fetchone()
    assert row is not None and row['event_id'] is None and row['invited_at'] is not None


def test_it_waits_at_most_5_seconds_for_its_lock_on_event():
    """The foreign key takes SHARE ROW EXCLUSIVE on event. Behind a deploy
    that finds an organiser's edit still open, the CREATE gives up after 5
    seconds rather than queue every later write on event behind it, as
    0077 does for push_tap. The same SQL under a scratch name, so the
    shared table is never dropped."""
    import time

    import database
    scratch = f'lead_join_invite_locktest_{uuid4().hex[:8]}'
    holder = psycopg.connect(database._api_conninfo)
    runner = psycopg.connect(database._api_conninfo)
    try:
        # The test connections cancel any statement after 5 seconds
        # (database._api_conninfo); the deploy's psql does not.
        runner.execute("SET statement_timeout = '30s'")
        runner.commit()
        holder.execute('LOCK TABLE event IN ROW EXCLUSIVE MODE')
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            runner.execute(SQL.replace('lead_join_invite', scratch))
        assert time.monotonic() - started < 15
        runner.rollback()
        holder.rollback()
        runner.execute(SQL.replace('lead_join_invite', scratch))
        assert runner.execute('SHOW lock_timeout').fetchone()[0] in ('0', '0ms')
        runner.rollback()
    finally:
        holder.close()
        runner.close()
