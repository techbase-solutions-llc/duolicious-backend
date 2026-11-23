"""TEC-2057: POST /checkout/web refuses a member who already has a live
Stripe subscription, so nobody can start a second one and be charged twice.

Stripe is mocked (no live Stripe, no DB): service.checkout._stripe and
service.checkout._customer_id_for are patched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import service.checkout as checkout


def _session(person_id=1):
    return SimpleNamespace(person_id=person_id, person_uuid='u-1')


def _req(tier='month'):
    return SimpleNamespace(tier_key=tier)


@pytest.fixture
def stripe_mock(monkeypatch):
    m = MagicMock(name='stripe')
    m.checkout.Session.create.return_value = SimpleNamespace(url='https://checkout.example/s')
    monkeypatch.setattr(checkout, '_stripe', lambda: m)
    monkeypatch.setenv('STRIPE_PRICE_PREMIUM_MONTH', 'price_test_month')
    return m


@pytest.mark.parametrize('status', ['active', 'trialing', 'past_due', 'unpaid', 'paused', 'incomplete'])
def test_live_subscription_is_refused(stripe_mock, monkeypatch, status):
    monkeypatch.setattr(checkout, '_customer_id_for', lambda pid: 'cus_123')
    stripe_mock.Subscription.list.return_value = {'data': [{'id': 'sub_1', 'status': status}]}

    out = checkout.post_checkout_web(_session(), _req())

    assert out == ({'error': 'already_subscribed'}, 409)
    stripe_mock.checkout.Session.create.assert_not_called()


def test_ended_subscription_can_subscribe_again(stripe_mock, monkeypatch):
    monkeypatch.setattr(checkout, '_customer_id_for', lambda pid: 'cus_123')
    stripe_mock.Subscription.list.return_value = {
        'data': [{'id': 'sub_1', 'status': 'canceled'}, {'id': 'sub_0', 'status': 'incomplete_expired'}],
    }

    out = checkout.post_checkout_web(_session(), _req())

    assert out == {'url': 'https://checkout.example/s'}


def test_member_without_stripe_customer_skips_the_lookup(stripe_mock, monkeypatch):
    monkeypatch.setattr(checkout, '_customer_id_for', lambda pid: None)

    out = checkout.post_checkout_web(_session(), _req())

    assert out == {'url': 'https://checkout.example/s'}
    stripe_mock.Subscription.list.assert_not_called()


def test_stripe_lookup_failure_does_not_block_checkout(stripe_mock, monkeypatch):
    monkeypatch.setattr(checkout, '_customer_id_for', lambda pid: 'cus_123')
    stripe_mock.Subscription.list.side_effect = RuntimeError('stripe down')

    out = checkout.post_checkout_web(_session(), _req())

    assert out == {'url': 'https://checkout.example/s'}
