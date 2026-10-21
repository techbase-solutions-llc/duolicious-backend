"""The API errors card (TEC-1897, health review finding 17): unhandled
errors per route, counted by the API's own error path. The route is the
Flask rule, so no id or address is ever stored."""
from __future__ import annotations

import pytest

from database import api_tx
from service.api import error_tally


def _errors(client, headers) -> dict:
    r = client.get('/admin/system/errors', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _route_count(body: dict, route: str) -> int:
    return next((r['errors'] for r in body['routes'] if r['route'] == route), 0)


@pytest.fixture(autouse=True)
def _own_rows():
    """The tally is shared: drop the made-up routes this file records."""
    yield
    with api_tx() as tx:
        tx.execute("DELETE FROM api_error_tally WHERE route IN ('/admin/users/<uuid>', '/anything')")


def test_the_card_is_for_admins_only(client, make_person, sign_in):
    r = client.get('/admin/system/errors', headers=sign_in(make_person(name='ErrMember')))
    assert r.status_code == 403


def test_an_unhandled_error_is_counted_under_its_rule(client, admin_bearer, monkeypatch):
    import service.api.admin.growth_routes as gr

    before = _errors(client, admin_bearer)

    def boom(tx):
        raise RuntimeError('boom')

    monkeypatch.setattr(gr, 'source_rows', boom)
    with pytest.raises(RuntimeError):
        client.get('/admin/growth/sources', headers=admin_bearer)
    after = _errors(client, admin_bearer)
    assert after['available'] is True
    assert after['last_24h'] - before['last_24h'] == 1
    assert after['last_7d'] - before['last_7d'] == 1
    assert (_route_count(after, '/admin/growth/sources')
            - _route_count(before, '/admin/growth/sources')) == 1
    row = next(r for r in after['routes'] if r['route'] == '/admin/growth/sources')
    assert row['last_failed_at'].endswith('+00:00')


def test_a_rule_with_an_id_is_stored_as_the_rule(client, admin_bearer):
    error_tally.record('/admin/users/<uuid>')
    body = _errors(client, admin_bearer)
    assert any(r['route'] == '/admin/users/<uuid>' for r in body['routes'])


def test_a_403_is_not_an_error(client, admin_bearer, make_person, sign_in):
    before = _errors(client, admin_bearer)['last_24h']
    client.get('/admin/growth/sources', headers=sign_in(make_person(name='ErrMember2')))
    assert _errors(client, admin_bearer)['last_24h'] == before


def test_a_tally_that_cannot_write_never_raises(monkeypatch, capsys):
    from contextlib import contextmanager

    @contextmanager
    def broken(*a, **k):
        raise OSError('database down')
        yield

    monkeypatch.setattr(error_tally, 'api_tx', broken)
    error_tally.record('/anything')
    assert 'not recorded' in capsys.readouterr().out


def test_the_card_says_when_the_counter_is_unavailable(client, admin_bearer, monkeypatch):
    import psycopg

    def missing(tx):
        raise psycopg.errors.UndefinedTable('api_error_tally')

    monkeypatch.setattr(error_tally, 'summary', missing)
    assert _errors(client, admin_bearer) == dict(
        available=False, last_24h=None, last_7d=None, routes=[])
