"""The Cohorts per-inviter table lists the members who share their link.

Until 13 Oct 2026 the table was built from beta_signup rows with the beta
intro sent, and joined clicks on the address the click logger stored. Every
member's own link carries person.referral_code, which is never in
beta_signup, so (health review findings 7, 25 and 73):

- the 32 members sent the intro by the referralintro cron since 1 Oct, who
  have no beta row, could never appear;
- 87 of the 128 clicks, all on member links, were counted against nobody;
- bot clicks (link previews) were counted as clicks, while the Overview's
  click-through leaves them out.

The table now starts from whoever holds a code, a member's or a beta-era
one, grouped by address, and counts clicks on the code itself. The output
columns are the ones the admin table already reads.

Each test makes its own holders and reads the table before and after where
it compares totals, because the test database is shared.
"""
from __future__ import annotations

import secrets
import uuid

import pytest

from database import api_tx
from service.admin.queries import Q_REFERRALS_KPIS, Q_REFERRALS_PER_INVITER
from service.campaigns import log_send

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ADMIN_COLUMNS = {'inviter', 'referral_code', 'clicks', 'signups', 'credited',
                 'pending_token_balance'}


def _code() -> str:
    return ''.join(secrets.choice(_ALPHABET) for _ in range(7))


def _table() -> dict:
    with api_tx('read committed') as tx:
        return {r['inviter']: dict(r) for r in tx.execute(Q_REFERRALS_PER_INVITER).fetchall()}


def _kpis() -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_REFERRALS_KPIS).fetchone())


@pytest.fixture
def made():
    """Codes, beta addresses and referral addresses to clear afterwards."""
    m = dict(codes=[], beta=[], referral=[])
    yield m
    with api_tx() as tx:
        tx.execute("DELETE FROM referral_link_click WHERE code = ANY(%(c)s)", dict(c=m['codes']))
        tx.execute("DELETE FROM referral WHERE inviter_email = ANY(%(e)s)", dict(e=m['referral']))
        tx.execute("DELETE FROM beta_signup WHERE email = ANY(%(e)s)", dict(e=m['beta']))


def _member(make_person, made, name: str) -> tuple[int, str, str]:
    p = make_person(name=name)
    code = _code()
    with api_tx() as tx:
        email = tx.execute(
            "UPDATE person SET referral_code = %(c)s WHERE id = %(i)s RETURNING email",
            dict(c=code, i=p['id'])).fetchone()['email']
    made['codes'].append(code)
    return p['id'], email, code


def _beta(made, email: str | None = None, intro_sent: bool = True) -> tuple[str, str]:
    email = email or f'per-inviter-{uuid.uuid4().hex[:10]}@example.com'
    code = _code()
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO beta_signup (email, referral_code, referral_intro_sent_at)
               VALUES (%(e)s, %(c)s, CASE WHEN %(s)s THEN NOW() END)""",
            dict(e=email, c=code, s=intro_sent))
    made['codes'].append(code)
    made['beta'].append(email)
    return email, code


def _intro_sent_by_cron(person_id: int) -> None:
    with api_tx() as tx:
        log_send(tx, person_id, 'referral', f'referral-{person_id}-2026w41', 'mid')


def _click(code: str, ua_class: str = 'mobile', inviter: str | None = None,
           well_formed: bool = True) -> None:
    """As the logger stored it. Clicks before 13 Oct carry no inviter."""
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO referral_link_click (code, inviter_email, well_formed, user_agent_class)
               VALUES (%(c)s, %(e)s, %(w)s, %(u)s)""",
            dict(c=code, e=inviter, w=well_formed, u=ua_class))


def test_a_member_sent_the_intro_by_the_cron_appears_with_their_clicks(make_person, made):
    """The case the old table could never show: a member with no beta row,
    whose intro is in the send log, and whose clicks carry no inviter."""
    pid, email, code = _member(make_person, made, 'CronSharer')
    _intro_sent_by_cron(pid)
    _click(code, 'mobile')
    _click(code, 'desktop')
    _click(code, 'mobile')
    _click(code, 'bot')
    _click(code, 'mobile', well_formed=False)

    row = _table()[email]

    assert set(row) == ADMIN_COLUMNS
    assert row['referral_code'] == code
    assert row['clicks'] == 3, 'bot and malformed clicks counted as clicks'


def test_a_member_with_clicks_appears_without_any_intro(make_person, made):
    """Someone who shares their link from the Invite screen, before the
    intro reaches them."""
    _pid, email, code = _member(make_person, made, 'EarlySharer')
    _click(code)
    assert _table()[email]['clicks'] == 1


def test_a_member_who_neither_had_the_intro_nor_shared_is_not_listed(make_person, made):
    _pid, email, _code_ = _member(make_person, made, 'Quiet')
    assert email not in _table()


def test_a_beta_tester_who_became_a_member_is_one_row_under_their_member_code(make_person, made):
    """Three production members also hold a beta code. Their row shows the
    link they share now, and counts clicks on both."""
    pid, email, code = _member(make_person, made, 'BetaThenMember')
    _beta_email, beta_code = _beta(made, email=email)
    _click(code)
    _click(code)
    _click(beta_code, inviter=email)

    rows = [r for r in _table().values() if r['inviter'] == email]

    assert len(rows) == 1
    assert rows[0]['referral_code'] == code
    assert rows[0]['clicks'] == 3


def test_a_beta_tester_sent_the_intro_is_still_listed(made):
    email, code = _beta(made)
    row = _table()[email]
    assert row['referral_code'] == code
    assert row['clicks'] == 0 and row['signups'] == 0


def test_a_beta_tester_never_sent_the_intro_and_never_clicked_is_not_listed(made):
    email, _code_ = _beta(made, intro_sent=False)
    assert email not in _table()


def test_signups_credits_and_pending_balance_are_the_members_own(make_person, made):
    pid, email, _code_ = _member(make_person, made, 'Recruiter')
    _intro_sent_by_cron(pid)
    with api_tx() as tx:
        for status in ('pending', 'graduated', 'credited'):
            tx.execute(
                """INSERT INTO referral (inviter_email, invitee_email, status)
                   VALUES (%(i)s, %(e)s, %(s)s)""",
                dict(i=email, e=f'invitee-{uuid.uuid4().hex[:10]}@example.com', s=status))
    made['referral'].append(email)

    row = _table()[email]

    assert row['signups'] == 3
    assert row['credited'] == 1
    assert row['pending_token_balance'] == 10


def test_total_clicks_leaves_out_bots_as_the_table_does(make_person, made):
    """One measure on the strip, the table and the Overview's click-through.
    The click-stream chart still draws bots as their own line."""
    _pid, _email, code = _member(make_person, made, 'BotMagnet')
    before = _kpis()
    _click(code, 'bot')
    _click(code, 'bot')
    assert _kpis()['total_clicks'] == before['total_clicks']
    assert _kpis()['distinct_codes_clicked'] == before['distinct_codes_clicked']
    _click(code, 'mobile')
    after = _kpis()
    assert after['total_clicks'] == before['total_clicks'] + 1
    assert after['distinct_codes_clicked'] == before['distinct_codes_clicked'] + 1
