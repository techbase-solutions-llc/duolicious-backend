"""Every member has a personal referral code (health review finding 77).

Four members who joined on 16 and 17 June had no person code. Three fell
back to a beta-era code; one had none, so /invite showed 'ahavah.app/i/'
with no code and Copy put the text 'null' on the clipboard.

  1. GET /referrals/me mints a code for a member who has none, so the
     invite screen never shows a missing code again.
  2. scripts/mint_missing_referral_codes.py mints one for each member who
     has none (staff accounts are left alone). Idempotent, counts only.
  3. Finishing onboarding still mints one in the same transaction.
"""
from __future__ import annotations

import pytest

from database import api_tx


class _Rollback(Exception):
    """Raised to roll the test's transaction back, so the script's run
    does not mint codes for unrelated people in the shared test database."""


def _code_of(tx, person_id: int):
    return tx.execute(
        'SELECT referral_code FROM person WHERE id = %(i)s', dict(i=person_id)
    ).fetchone()['referral_code']


def _email_of(tx, person_id: int) -> str:
    return tx.execute(
        'SELECT email FROM person WHERE id = %(i)s', dict(i=person_id)
    ).fetchone()['email']


# --- 1. GET /referrals/me -------------------------------------------------

def test_the_invite_screen_mints_a_code_for_a_member_with_none(make_person):
    from service.referrals import get_my_referrals

    member = make_person(name='Codeless', gender='Woman')

    with api_tx() as tx:
        assert _code_of(tx, member['id']) is None

        out = get_my_referrals(tx, member['uuid'])
        code = _code_of(tx, member['id'])

        assert code and len(code) == 7, 'no code was minted'
        assert out['code'] == code
        assert out['link'] == f'https://ahavah.app/i/{code}'

        again = get_my_referrals(tx, member['uuid'])
        assert again['code'] == code, 'a second visit changed the code'


def test_a_member_with_only_a_beta_code_gets_a_person_code(make_person):
    from service.referrals import get_my_referrals, inviter_email_for_code

    member = make_person(name='Beta', gender='Man')

    with api_tx() as tx:
        email = _email_of(tx, member['id'])
        tx.execute(
            "INSERT INTO beta_signup (email, referral_code) VALUES (%(e)s, 'BETA777')",
            dict(e=email))
        try:
            out = get_my_referrals(tx, member['uuid'])
            code = _code_of(tx, member['id'])
            assert code and out['code'] == code
            assert out['link'] == f'https://ahavah.app/i/{code}'
            # A beta link the member already shared still finds them.
            assert inviter_email_for_code(tx, 'BETA777') == email
        finally:
            tx.execute('DELETE FROM beta_signup WHERE email = %(e)s', dict(e=email))


# --- 2. The one-off script --------------------------------------------------

def test_the_script_mints_codes_for_members_only_and_is_idempotent(make_person):
    from scripts.mint_missing_referral_codes import mint_missing

    member = make_person(name='Missing', gender='Woman')
    staff = make_person(name='Operator', gender='Man')

    with pytest.raises(_Rollback):
        with api_tx() as tx:
            tx.execute(
                "UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(i)s",
                dict(i=staff['id']))

            dry = mint_missing(tx, dry_run=True)
            assert dry['would_mint'] >= 1
            assert dry['staff_without_code'] >= 1
            assert _code_of(tx, member['id']) is None, 'a dry run wrote a code'

            done = mint_missing(tx)
            assert done['minted'] == dry['would_mint']
            assert _code_of(tx, member['id']), 'the member got no code'
            assert _code_of(tx, staff['id']) is None, 'a staff account got a code'

            again = mint_missing(tx)
            assert again['minted'] == 0, 'a second run minted again'

            raise _Rollback


# --- 3. A new member -------------------------------------------------------

def test_finishing_onboarding_mints_a_code(finish_onboarding):
    r, person_id = finish_onboarding()
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx() as tx:
        code = _code_of(tx, person_id)
    assert code and len(code) == 7


def test_the_route_mints_under_read_committed(client, make_person, sign_in, monkeypatch):
    """Two first loads of /invite at once could both find no code and both
    mint. Under the default REPEATABLE READ the second one's retry loop
    saw only its own snapshot and raised ReferralCodeCollision, a 500. The
    route now opens its transaction at READ COMMITTED, so the retry sees
    the code the first load stored and returns it."""
    import service.api.referrals_routes as routes

    levels = []
    real_api_tx = routes.api_tx

    def recording_api_tx(*args, **kwargs):
        levels.append(args[0].upper() if args else 'DEFAULT')
        return real_api_tx(*args, **kwargs)

    monkeypatch.setattr(routes, 'api_tx', recording_api_tx)

    member = make_person(name='RouteMint', gender='Woman')
    r = client.get('/referrals/me', headers=sign_in(member))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    with api_tx() as tx:
        code = _code_of(tx, member['id'])
    assert code and body['code'] == code
    assert body['link'] == f'https://ahavah.app/i/{code}'
    assert levels == ['READ COMMITTED']
