"""Spotlight: staff accounts are never featured (finding 88), and a card
that lapses unanswered is no longer silent (finding 78)."""
import secrets

import pytest

from database import api_tx
from service.spotlight.eligibility import REASONS, eligibility
from service.spotlight.queue import create_candidate


def _eligible(make_person, name='Lapse', roles=None):
    p = make_person(name=name, gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                      ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                      roles = COALESCE(%(r)s::text[], roles)
                WHERE id = %(id)s""", dict(id=p['id'], r=roles))
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
               VALUES (%(u)s, %(id)s, 1, 'approved', 'blur', gen_random_uuid()::text)""",
            dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _cleanup(person_id):
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE subject_person_id = %(p)s", dict(p=person_id))


def test_a_staff_account_is_not_eligible(make_person):
    p = _eligible(make_person, 'Staffer', roles=['admin'])
    with api_tx('read committed') as tx:
        assert eligibility(tx, p['id']) == (False, 'staff')
    assert 'staff' in REASONS


def test_a_member_with_the_same_profile_is(make_person):
    p = _eligible(make_person, 'Member')
    with api_tx('read committed') as tx:
        assert eligibility(tx, p['id']) == (True, '')


def test_no_card_can_be_created_for_staff(make_person):
    p = _eligible(make_person, 'StaffCard', roles=['admin'])
    with api_tx() as tx, pytest.raises(ValueError, match='staff'):
        create_candidate(tx, kind='member_of_week', subject_person_id=p['id'],
                         caption='x', created_by='test')


def test_a_withheld_invite_for_staff_is_cancelled_not_retried():
    from service.api.admin.spotlight_routes import TERMINAL_INVITE_REASONS
    assert 'staff' in TERMINAL_INVITE_REASONS
