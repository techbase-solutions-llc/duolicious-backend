"""A profile save that loses every retry to a busy row answers 409, not 500
(TEC-2111, 5 Nov 2026).

One member's phone sent hundreds of PATCH /profile-info requests at once.
api_tx is REPEATABLE READ, so writes to the same person row abort each
other with SerializationFailure; the server retries three times, and 42 of
them still failed and answered 500. A 500 reads as a fault. The web client
now queues its saves, and when the row stays busy the API answers 409 with
`Retry-After: 2` so the client waits and sends the latest value once.

Every PATCH /profile-info also logs the field name (never the value) so the
next incident can be split by field.
"""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager

import psycopg
import pytest

import service.person as person
from database import api_tx


@pytest.fixture
def quiet(monkeypatch):
    """No rate limit, and no presence bump: the bump is its own write to the
    person row, which would add an unplanned transaction to each request."""
    from service.api.decorators import limiter
    monkeypatch.setattr(limiter, 'enabled', False)
    monkeypatch.setattr(person, 'bump_presence', lambda person_id: None)


def _row(person_id: int) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute(
            'SELECT name, about, ahavah_extra FROM person WHERE id = %(i)s',
            dict(i=person_id)).fetchone()


def _ahavah_extra(person_id: int) -> dict:
    extra = _row(person_id)['ahavah_extra'] or {}
    return extra if isinstance(extra, dict) else json.loads(extra)


# A writer that never lets go of the row: every transaction the save opens
# takes its snapshot, then another connection updates the same row and
# commits. The save's own UPDATE then meets a row changed after its
# snapshot, and Postgres aborts it with a real SerializationFailure, on
# every attempt.

def _always_busy(monkeypatch, person_id: int) -> dict:
    import database
    real = person.api_tx
    calls = {'n': 0}

    @contextmanager
    def busy(*a, **k):
        calls['n'] += 1
        with real(*a, **k) as tx:
            tx.execute('SELECT 1')
            with psycopg.connect(database._api_conninfo, autocommit=True) as other:
                other.execute(
                    'UPDATE person SET last_online_time = now() WHERE id = %(i)s',
                    dict(i=person_id))
            yield tx

    monkeypatch.setattr(person, 'api_tx', busy)
    return calls


@pytest.mark.parametrize('body', [
    {'ahavah_extra': {'assembly': 'natsarim'}},
    {'name': 'Busy Row'},
    {'about': 'A bio written while the row was busy'},
], ids=['ahavah_extra', 'name', 'about'])
def test_a_save_that_loses_every_retry_answers_409_with_retry_after(
        client, make_person, sign_in, quiet, monkeypatch, body):
    p = make_person(name='Before')
    headers = sign_in(p)
    before = _row(p['id'])
    calls = _always_busy(monkeypatch, p['id'])

    r = client.patch('/profile-info', headers=headers, json=body)

    assert r.status_code == 409, r.get_data(as_text=True)
    assert r.headers.get('Retry-After') == '2'
    assert r.get_json() == {'error': 'busy'}
    assert calls['n'] == 3, 'the existing retries still run before the 409'
    assert _row(p['id']) == before, 'nothing was written'


def test_the_bio_helper_answers_busy_instead_of_raising(make_person, monkeypatch):
    p = make_person(name='BioBusy')
    _always_busy(monkeypatch, p['id'])

    result = person._patch_profile_info_about(p['id'], 'Never lands')

    assert result == ({'error': 'busy'}, 409, {'Retry-After': '2'})
    assert _row(p['id'])['about'] == 'about'


# Two PATCHes to the same row at the same moment, through the real Flask
# client, each with its own connection the way separate API workers hold
# theirs in production. The test client otherwise shares one connection
# behind a lock, so nothing could overlap. Copied from
# tests/test_growth_routes.py: test files here do not import each other.

def _one_connection_per_tx(m, on_enter=None):
    import database

    def _enter(self):
        self._own_conn = psycopg.Connection.connect(
            conninfo=database._api_conninfo, row_factory=psycopg.rows.dict_row)
        self.cur = self._own_conn.cursor()
        if self.isolation_level != database._default_transaction_isolation:
            self.cur.execute(f'SET TRANSACTION ISOLATION LEVEL {self.isolation_level}')
        if on_enter is not None:
            on_enter(self)
        return self.cur

    def _exit(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._own_conn.commit()
            else:
                self._own_conn.rollback()
        finally:
            self._own_conn.close()

    m.setattr(database.api_tx, '__enter__', _enter)
    m.setattr(database.api_tx, '__exit__', _exit)


def test_two_concurrent_saves_to_one_row_both_land_or_the_loser_gets_409(
        app, make_person, sign_in, quiet, monkeypatch):
    import database
    p = make_person(name='Before')
    headers = sign_in(p)

    # Both saves take their snapshot before either writes, so the second
    # writer is certain to meet the first one's committed change.
    barrier = threading.Barrier(2)
    met = threading.local()
    writes = {'n': 0}
    lock = threading.Lock()

    def on_enter(tx):
        if tx.isolation_level != database._default_transaction_isolation:
            return
        with lock:
            writes['n'] += 1
        if not getattr(met, 'done', False):
            met.done = True
            tx.cur.execute('SELECT 1')
            barrier.wait(timeout=30)

    bodies = [
        {'ahavah_extra': {'assembly': 'natsarim'}},
        {'name': 'After'},
    ]

    results: list = [None, None]

    def worker(i):
        with app.test_client() as c:
            try:
                r = c.patch('/profile-info', headers=headers, json=bodies[i])
                results[i] = (r.status_code, dict(r.headers), r.get_json(silent=True))
            except Exception as e:      # noqa: BLE001 -- recorded as the evidence
                results[i] = (type(e).__name__, {}, None)

    with monkeypatch.context() as m:
        _one_connection_per_tx(m, on_enter)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=60)

    statuses = [s for s, _, _ in results]
    assert all(s in (200, 409) for s in statuses), results
    assert writes['n'] >= 3, 'the race must have made one save retry'

    row = _row(p['id'])
    extra_status, name_status = statuses
    if extra_status == 200:
        assert _ahavah_extra(p['id']).get('assembly') == 'natsarim'
    if name_status == 200:
        assert row['name'] == 'After'
    for status, hdrs, body in results:
        if status == 409:
            assert hdrs.get('Retry-After') == '2'
            assert body == {'error': 'busy'}


def test_each_save_logs_its_field_name_and_never_the_value(
        client, make_person, sign_in, quiet, caplog):
    p = make_person(name='Logged')
    headers = sign_in(p)
    secret = 'value-that-must-never-be-logged'

    with caplog.at_level(logging.INFO, logger='service.person'):
        r = client.patch('/profile-info', headers=headers,
                         json={'ahavah_extra': {'note': secret}})

    assert r.status_code == 200, r.get_data(as_text=True)
    lines = [rec for rec in caplog.records
             if rec.name == 'service.person' and rec.levelno == logging.INFO]
    assert len(lines) == 1, [rec.getMessage() for rec in lines]
    message = lines[0].getMessage()
    assert 'field=ahavah_extra' in message
    assert '\n' not in message
    assert secret not in caplog.text
    assert str(p['id']) not in message
    assert p['uuid'] not in message


def test_the_browser_can_read_retry_after():
    # The web app is on another origin; without this a script never sees
    # Retry-After and always falls back to its own guess (TEC-2111).
    from service.api.decorators import app
    with app.test_client() as c:
        r = c.get('/health', headers={'Origin': 'https://ahavah.app'})
    exposed = r.headers.get('Access-Control-Expose-Headers', '')
    assert 'retry-after' in exposed.lower()
