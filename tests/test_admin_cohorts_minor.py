"""Cohorts: the API half of the admin audit's Minor findings (TEC-1845,
21 Oct).

- A beta tester sent the intro by the referralintro cron counts as sent:
  the cron records its sends in email_send_log and never sets
  beta_signup.referral_intro_sent_at, which the KPIs and rows read alone
  (Minor 28).
- The per-inviter pending balance is REFERRAL_REWARD_TOKENS a referral,
  not a literal 5 (Minor 31)."""
from __future__ import annotations

import importlib
import uuid

import pytest

from database import api_tx


def _beta_kpis() -> dict:
    from service.admin.queries.cohorts import Q_BETA_KPIS
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_BETA_KPIS).fetchone())


def _beta_row(email: str) -> dict:
    from service.admin.queries.cohorts import Q_BETA_ROWS
    unlimited = Q_BETA_ROWS.replace('LIMIT 100', 'LIMIT 1000000')
    with api_tx('read committed') as tx:
        return next(dict(r) for r in tx.execute(unlimited).fetchall() if r['email'] == email)


@pytest.fixture
def beta_member(make_person):
    """A beta tester who became a member, with no beta intro on file."""
    made: list[str] = []

    def _make() -> tuple[dict, str]:
        email = f'beta-minor-{uuid.uuid4().hex[:10]}@example.com'
        p = make_person(name='BetaMinor', email=email)
        with api_tx() as tx:
            tx.execute("INSERT INTO beta_signup (email) VALUES (%(e)s)", dict(e=email))
        made.append(email)
        return p, email

    yield _make
    with api_tx() as tx:
        tx.execute("DELETE FROM beta_signup WHERE email = ANY(%(e)s)", dict(e=made))


def _log_cron_intro(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id)
                      VALUES (%(p)s, 'referral', %(c)s)""",
                   dict(p=person_id, c=f'referral-{uuid.uuid4().hex[:8]}'))


def test_the_crons_intro_counts_as_sent(beta_member):
    before = _beta_kpis()
    p, email = beta_member()
    mid = _beta_kpis()
    assert mid['never_emailed'] == before['never_emailed'] + 1
    _log_cron_intro(p['id'])
    after = _beta_kpis()
    assert after['intro_sent'] == before['intro_sent'] + 1
    assert after['never_emailed'] == before['never_emailed']
    assert _beta_row(email)['referral_intro_sent_at'] is not None


def test_a_tester_with_no_intro_reads_never_emailed(beta_member):
    _p, email = beta_member()
    assert _beta_row(email)['referral_intro_sent_at'] is None


def test_the_pending_balance_follows_the_reward(make_person, monkeypatch):
    import service.referrals as referrals
    import service.admin.queries.cohorts as cohorts
    email = f'inviter-minor-{uuid.uuid4().hex[:10]}@example.com'
    make_person(name='InviterMinor', email=email)
    with api_tx() as tx:
        tx.execute("UPDATE person SET referral_code = %(c)s WHERE email = %(e)s",
                   dict(c=f'm{uuid.uuid4().hex[:9]}', e=email))
        tx.execute("""INSERT INTO referral (inviter_email, invitee_email, status)
                      VALUES (%(i)s, %(e)s, 'pending')""",
                   dict(i=email, e=f'invitee-minor-{uuid.uuid4().hex[:10]}@example.com'))
    try:
        monkeypatch.setattr(referrals, 'REFERRAL_REWARD_TOKENS', 7)
        importlib.reload(cohorts)
        q = cohorts.Q_REFERRALS_PER_INVITER.replace('LIMIT 50', 'LIMIT 1000000')
        with api_tx('read committed') as tx:
            row = next(r for r in tx.execute(q).fetchall() if r['inviter'] == email)
        assert row['pending_token_balance'] == 7
    finally:
        monkeypatch.undo()
        importlib.reload(cohorts)
        with api_tx() as tx:
            tx.execute("DELETE FROM referral WHERE inviter_email = %(e)s", dict(e=email))
