"""Premium adds count each new subscription once (TEC-1845 audit, serious 4).

One Stripe subscription checkout sends checkout.session.completed AND
customer.subscription.created, and a token bundle is a checkout.session.
completed too (mode 'payment'). The chart counted all three kinds, so one
subscriber plotted as 2 adds and every bundle as 1. It now counts only a
checkout.session.completed whose session mode is 'subscription'."""
from __future__ import annotations

import json
import uuid

from database import api_tx
from service.admin.queries import Q_OVERVIEW_PREMIUM_30D


def _adds_today() -> int:
    with api_tx('read committed') as tx:
        return tx.execute(Q_OVERVIEW_PREMIUM_30D).fetchall()[-1]['adds']


def _event(person_id: int, event_type: str, obj: dict) -> None:
    payload = {'livemode': True, 'type': event_type, 'data': {'object': obj}}
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(eid)s, %(t)s, %(uid)s, %(pl)s::jsonb,
                       ((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '09:00')
                       AT TIME ZONE 'America/Barbados')""",
            dict(eid=f'test-adds-{uuid.uuid4()}', t=event_type, uid=str(person_id),
                 pl=json.dumps(payload)))


def test_one_subscription_checkout_is_one_add(make_person):
    p = make_person(name='Subscriber')
    before = _adds_today()
    _event(p['id'], 'checkout.session.completed',
           {'object': 'checkout.session', 'mode': 'subscription', 'livemode': True})
    _event(p['id'], 'customer.subscription.created',
           {'object': 'subscription', 'livemode': True})
    assert _adds_today() == before + 1


def test_a_token_bundle_is_not_a_premium_add(make_person):
    p = make_person(name='BundleBuyer')
    before = _adds_today()
    _event(p['id'], 'checkout.session.completed',
           {'object': 'checkout.session', 'mode': 'payment', 'livemode': True})
    assert _adds_today() == before


def test_the_mode_is_read_where_a_payload_stored_as_the_object_keeps_it(make_person):
    p = make_person(name='ObjectPayload')
    before = _adds_today()
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s,
                       '{"livemode": true, "mode": "subscription"}'::jsonb,
                       ((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '09:00')
                       AT TIME ZONE 'America/Barbados')""",
            dict(eid=f'test-adds-{uuid.uuid4()}', uid=str(p['id'])))
    assert _adds_today() == before + 1
