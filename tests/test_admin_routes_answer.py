"""Every admin GET route answers 200 with a JSON body.

Economy > Entitlement holders returned 500 on every load from the day it
shipped until 13 Oct 2026. The query selected `subscription_expires_at -
NOW()`, psycopg hands an interval back as a Python timedelta, and Flask's
JSON provider cannot encode one, so the response died after the query had
already succeeded. No test called the route with a holder that had an
expiry date, and the admin showed "Couldn't load entitlements".

This walks the Flask URL map rather than a hand-kept list, so a GET route
added under /admin later is called here without anyone remembering to add
it. A parameterised route must name its arguments in `_ARGS`; one that does
not fails the test, which is the point.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

import pytest

from database import api_tx


# Signed links from moderation emails, not dashboard routes. They take a
# one-time token in the path and are meant to refuse a made-up one, so they
# are covered by their own tests and not by an admin session.
_NOT_SESSION_ROUTES = {
    '/admin/ban-link/<token>',
    '/admin/delete-photo-link/<token>',
}


def _args(admin_uuid: str) -> dict[str, dict]:
    return {
        '/admin/users/<uuid>': dict(uuid=admin_uuid),
        # An unknown run answers a row of zero counts, not a 404.
        '/admin/growth/emails/<campaign>/status/<campaign_id>':
            dict(campaign='e2', campaign_id=f'no-such-run-{uuid.uuid4().hex[:8]}'),
        # An unknown queue row answers ok=false, reason=not_found.
        '/admin/growth/queue/<qid>/eligible': dict(qid=str(uuid.uuid4())),
        # An unknown gathering answers no weeks, not a 404 (TEC-1845).
        '/admin/events/<slug>/weeks': dict(slug=f'no-such-gathering-{uuid.uuid4().hex[:8]}'),
        # Matchmaker (TEC-1845): a member's connections, by uuid or id.
        '/admin/users/<who>/connections': dict(who=admin_uuid),
    }


@pytest.fixture
def admin(make_person):
    p = make_person(name='RoutesAdmin')
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
    return dict(uuid=p['uuid'], headers={'Authorization': f'Bearer {tok}'})


@pytest.fixture
def premium_member(make_person):
    """A member whose Premium runs out in five days: the row that made the
    entitlements route fail, since every such row carried a timedelta."""
    p = make_person(name='RoutesPremium')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person
                  SET entitlements = ARRAY['premium']::TEXT[],
                      subscription_expires_at = NOW() + interval '5 days',
                      stripe_customer_id = 'cus_routes_test'
                WHERE id = %(i)s""",
            dict(i=p['id']))
    return p


def _admin_get_rules(app) -> list[str]:
    return sorted({r.rule for r in app.url_map.iter_rules()
                   if r.rule.startswith('/admin') and 'GET' in r.methods})


def test_every_admin_get_route_answers_200_with_json(app, client, admin, premium_member):
    args = _args(admin['uuid'])
    failures = []
    for rule in _admin_get_rules(app):
        if rule in _NOT_SESSION_ROUTES:
            continue
        path = rule
        if '<' in rule:
            if rule not in args:
                failures.append(f'{rule}: no arguments in _ARGS, so it is not being called')
                continue
            for name, value in args[rule].items():
                path = path.replace(f'<{name}>', value)
        # The test app propagates exceptions instead of turning them into a
        # 500, so catch them here and keep going: one broken route must not
        # hide the next.
        try:
            r = client.get(path, headers=admin['headers'])
        except Exception as e:
            failures.append(f'{path}: raised {type(e).__name__}: {e}')
            continue
        if r.status_code != 200:
            failures.append(f'{path}: {r.status_code}')
        elif not r.is_json or r.get_json(silent=True) is None:
            failures.append(f'{path}: 200 but not a JSON body')
    assert failures == [], '\n'.join(failures)


def test_entitlement_holders_carry_time_left_in_whole_seconds(client, admin, premium_member):
    """The fix for the 500: seconds, as an integer, which every JSON reader
    can take. The admin works days out from subscription_expires_at anyway."""
    r = client.get('/admin/economy/entitlements?name=premium&expires_within_days=6',
                   headers=admin['headers'])
    assert r.status_code == 200
    row = next(h for h in r.get_json()['holders'] if h['person_uuid'] == premium_member['uuid'])
    assert isinstance(row['time_left'], int)
    five_days = 5 * 24 * 3600
    assert five_days - 120 <= row['time_left'] <= five_days


def test_an_expired_holder_has_a_negative_time_left_not_an_error(client, admin, make_person):
    p = make_person(name='RoutesLapsed')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person
                  SET entitlements = ARRAY['premium']::TEXT[],
                      subscription_expires_at = NOW() - interval '2 days'
                WHERE id = %(i)s""",
            dict(i=p['id']))
    r = client.get('/admin/economy/entitlements?name=premium&expires_within_days=1',
                   headers=admin['headers'])
    assert r.status_code == 200
    row = next(h for h in r.get_json()['holders'] if h['person_uuid'] == p['uuid'])
    assert isinstance(row['time_left'], int) and row['time_left'] < 0
