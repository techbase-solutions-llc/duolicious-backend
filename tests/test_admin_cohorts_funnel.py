"""The beta funnel has an onboarding step that can differ from the next one.

Until 13 Oct 2026 the funnel's last two steps, "Person" and "Completed",
were the same count by construction: beta rows with a person, and persons
with a beta row, are the same set of email pairs when both columns are
unique. Both read 22, and the funnel could only ever show 100% from one to
the other. The stage it never showed is the one the Conversion notes beside
it describe: signed in and started onboarding, not yet finished.

A person row is written when onboarding finishes, and an `onboardee` row
exists from the first sign-in until then (service/person/sql). So
started_onboarding is a beta address with either, and completed_onboarding
is a beta address with a member's person row.
"""
from __future__ import annotations

import uuid

import pytest

from database import api_tx
from service.admin.queries import Q_BETA_FUNNEL


def _funnel() -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_BETA_FUNNEL).fetchone())


@pytest.fixture
def beta():
    made: list[str] = []

    def _make() -> str:
        e = f'funnel-{uuid.uuid4().hex[:10]}@example.com'
        with api_tx() as tx:
            tx.execute("INSERT INTO beta_signup (email) VALUES (%(e)s)", dict(e=e))
        made.append(e)
        return e

    yield _make
    with api_tx() as tx:
        for e in made:
            tx.execute("DELETE FROM onboardee WHERE email = %(e)s", dict(e=e))
            tx.execute("DELETE FROM beta_signup WHERE email = %(e)s", dict(e=e))


def test_signing_in_starts_onboarding_but_does_not_complete_it(beta):
    before = _funnel()
    e = beta()
    with api_tx() as tx:
        tx.execute("INSERT INTO onboardee (email) VALUES (%(e)s)", dict(e=e))
    after = _funnel()
    assert after['beta_total'] == before['beta_total'] + 1
    assert after['started_onboarding'] == before['started_onboarding'] + 1
    assert after['completed_onboarding'] == before['completed_onboarding'], \
        'started but unfinished must not read as completed'


def test_finishing_onboarding_counts_as_started_and_completed(beta, make_person):
    before = _funnel()
    e = beta()
    make_person(name='FunnelDone', email=e)
    after = _funnel()
    assert after['started_onboarding'] == before['started_onboarding'] + 1
    assert after['completed_onboarding'] == before['completed_onboarding'] + 1


def test_a_beta_address_that_never_signed_in_is_neither(beta):
    before = _funnel()
    beta()
    after = _funnel()
    assert after['beta_total'] == before['beta_total'] + 1
    assert after['started_onboarding'] == before['started_onboarding']
    assert after['completed_onboarding'] == before['completed_onboarding']


def test_each_step_is_inside_the_one_before():
    f = _funnel()
    assert f['beta_total'] >= f['started_onboarding'] >= f['completed_onboarding']
