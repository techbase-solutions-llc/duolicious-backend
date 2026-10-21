"""Expiring entitlement counts leave out holders who have already lapsed
(TEC-1845 admin audit, Minor 32). Between expiry and the nightly strip a
lapsed holder still holds the entitlement, and with no lower bound it
counted as expiring soon."""
from __future__ import annotations

from database import api_tx
from service.admin.queries.economy import Q_ENTITLEMENT_HOLDERS, Q_ENTITLEMENT_KPIS


def _kpis() -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_ENTITLEMENT_KPIS, dict(name='premium')).fetchone())


def _expiring_within(days: int) -> set[str]:
    q = Q_ENTITLEMENT_HOLDERS.replace('LIMIT 200', 'LIMIT 1000000')
    with api_tx('read committed') as tx:
        return {r['person_uuid'] for r in tx.execute(
            q, dict(name='premium', expires_within_days=days)).fetchall()}


def _premium_until(person_id: int, interval: str) -> None:
    with api_tx() as tx:
        tx.execute(f"""UPDATE person SET entitlements = ARRAY['premium']::TEXT[],
                              subscription_expires_at = NOW() + INTERVAL '{interval}'
                        WHERE id = %(i)s""", dict(i=person_id))


def test_a_lapsed_holder_is_not_expiring(make_person):
    before = _kpis()
    p = make_person(name='Lapsed')
    _premium_until(p['id'], '-1 hour')
    after = _kpis()
    assert after['holders'] == before['holders'] + 1
    assert (after['expiring_7d'], after['expiring_30d']) == (before['expiring_7d'], before['expiring_30d'])
    assert p['uuid'] not in _expiring_within(7)
    assert p['uuid'] in _expiring_within(0), 'the unfiltered list still shows the lapsed holder'


def test_a_holder_expiring_in_two_days_is_expiring(make_person):
    before = _kpis()
    p = make_person(name='Expiring')
    _premium_until(p['id'], '2 days')
    after = _kpis()
    assert (after['expiring_7d'], after['expiring_30d']) == (before['expiring_7d'] + 1, before['expiring_30d'] + 1)
    assert p['uuid'] in _expiring_within(7)
