"""The 000000 sign-in code is for development only (TEC-2042, 11 Nov 2026).

_OTP_CTE gave the zero code to any registered @example.com address even in
production: (example AND registered) OR (example AND is_dev). Production
had no such account, but anyone who registered one could sign in to it
with 000000. Now the zero code needs is_dev, whatever the address.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service.person.sql import _OTP_CTE


def _otp(email: str, is_dev: bool) -> str:
    with api_tx() as tx:
        return tx.execute(
            _OTP_CTE + ' SELECT otp FROM otp',
            dict(email=email, normalized_email=email, is_dev=is_dev,
                 ip_address='192.0.2.1')).fetchone()['otp']


@pytest.mark.parametrize('registered', [True, False])
def test_production_never_hands_out_the_zero_code(make_person, registered):
    email = 'zero-code-prod@example.com'
    if registered:
        make_person(name='ZeroProd', email=email)
    # Three draws, so a random 000000 (one in a million) cannot pass it.
    assert any(_otp(email, is_dev=False) != '000000' for _ in range(3))
    assert all(len(_otp(email, is_dev=False)) == 6 for _ in range(3))


@pytest.mark.parametrize('registered', [True, False])
def test_development_hands_out_the_zero_code_to_example_addresses(make_person, registered):
    email = 'zero-code-dev@example.com'
    if registered:
        make_person(name='ZeroDev', email=email)
    assert _otp(email, is_dev=True) == '000000'


def test_development_gives_other_addresses_a_random_code():
    assert any(_otp('someone@ahavah-test.invalid', is_dev=True) != '000000' for _ in range(3))
