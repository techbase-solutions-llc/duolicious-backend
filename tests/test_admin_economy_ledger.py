"""The Economy ledger table and the KPIs above it cover the same period.

Until 13 Oct 2026 the table and its "N entries" footer were silently
limited to the last 30 days (the route defaulted `days` to 30 and the admin
never sends it), while Total credits, Total debits and Circulation above it
summed every row ever written. The footer read 44 entries under KPIs built
from 127, and filtering on reason "purchase" said "No ledger rows match"
although 5 purchases existed, all older than 30 days.

Now the default period is all time, for the table and the KPIs alike. A
caller that asks for `days` gets the table AND the credits and debits for
that window, and the response says which period it is. Circulation is the
balance of every token ever issued, a stock rather than a flow, so it is
all time whatever the window.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='LedgerAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _ledger(person_uuid: str, delta: int, reason: str, days_ago: int) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO token_ledger (person_id, delta, reason, created_at)
               VALUES (%(p)s::uuid, %(d)s, %(r)s, NOW() - make_interval(days => %(a)s))""",
            dict(p=person_uuid, d=delta, r=reason, a=days_ago))


def _get(client, headers, query: str = '') -> dict:
    r = client.get(f'/admin/economy/ledger{query}', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _sums(days: int | None) -> dict:
    """The truth, straight from the table."""
    window = '' if not days else f"WHERE created_at > NOW() - make_interval(days => {int(days)})"
    with api_tx('read committed') as tx:
        return dict(tx.execute(f"""
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(delta) FILTER (WHERE delta > 0), 0)::int AS credits,
                   COALESCE(SUM(delta) FILTER (WHERE delta < 0), 0)::int AS debits
              FROM token_ledger {window}""").fetchone())


def test_by_default_the_table_and_the_kpis_are_both_all_time(client, admin_headers, make_person):
    p = make_person(name='LedgerOld')
    _ledger(p['uuid'], 40, 'purchase', days_ago=45)
    _ledger(p['uuid'], -3, 'boost', days_ago=44)

    body = _get(client, admin_headers)
    truth = _sums(None)
    assert body['total'] == truth['n'], 'the footer must count the rows the KPIs sum'
    assert body['kpis']['total_credits'] == truth['credits']
    assert body['kpis']['total_debits'] == truth['debits']
    assert body['days'] == 0


def test_an_old_purchase_is_found_by_its_reason(client, admin_headers, make_person):
    """The defect as the owner would meet it: 'No ledger rows match' for a
    purchase that is simply older than 30 days."""
    p = make_person(name='LedgerPurchase')
    _ledger(p['uuid'], 40, 'purchase', days_ago=60)
    body = _get(client, admin_headers, '?reason=purchase')
    assert body['total'] >= 1
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
    body = _get(client, admin_headers, f'?reason=purchase&email={email}')
    assert body['total'] == 1 and body['rows'][0]['person_uuid'] == p['uuid']


def test_a_window_narrows_the_table_and_the_kpis_together(client, admin_headers, make_person):
    p = make_person(name='LedgerWindow')
    _ledger(p['uuid'], 40, 'purchase', days_ago=45)
    _ledger(p['uuid'], 7, 'subscription_stipend', days_ago=2)
    _ledger(p['uuid'], -2, 'boost', days_ago=1)

    body = _get(client, admin_headers, '?days=30')
    truth = _sums(30)
    assert body['days'] == 30
    assert body['total'] == truth['n']
    assert body['kpis']['total_credits'] == truth['credits']
    assert body['kpis']['total_debits'] == truth['debits']
    # Circulation is the balance, all time, whatever the window.
    everything = _sums(None)
    assert body['kpis']['circulation'] == everything['credits'] + everything['debits']
