"""Leads: an email given to Ahavah before joining (TEC-1845).

One row per address and source; a member is never a lead; marketing
consent is a ticked box stored with its wording and never withdrawn by a
later unticked one; a confirm link is stored as a hash, works more than
once while it lasts and confirms nothing once it has lapsed or if it was
never issued.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest

from database import api_tx
from service.leads import (confirm_by_token, confirm_lead, issue_confirm_token,
                           lead_unsubscribed, record_lead, touch_lead)

pytestmark = pytest.mark.usefixtures('growth_schema')


@pytest.fixture
def addresses():
    made: list[str] = []

    def keep(address: str) -> str:
        made.append(address.lower())
        return address

    def new(domain: str = 'example.org') -> str:
        return keep(f'lead{uuid4().hex[:10]}@{domain}')

    yield SimpleNamespace(new=new, keep=keep)
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s) OR normalized_email = ANY(%(e)s)',
                   dict(e=made))


def _lead(lead_id: int) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM lead WHERE id = %(i)s', dict(i=lead_id)).fetchone()


def test_a_new_address_is_one_lead_per_source(addresses):
    email = addresses.new()
    with api_tx() as tx:
        a = record_lead(tx, email=email, source='tool:game-me')
        b = record_lead(tx, email=email, source='event:sukkot-2027')
        again = record_lead(tx, email=f'  {email.upper()} ', source='tool:game-me')
    assert a != b and again == a
    row = _lead(a)
    assert row['email'] == email and row['source'] == 'tool:game-me'
    assert row['marketing_consent'] is False and row['confirmed_at'] is None


def test_one_address_written_two_ways_is_one_lead(addresses):
    name = f'ann{uuid4().hex[:8]}'
    plain = addresses.keep(f'{name}@gmail.com')
    dotted = addresses.keep(f'{name[:3]}.{name[3:]}+tools@gmail.com')
    with api_tx() as tx:
        first = record_lead(tx, email=plain, source='alert:visitor')
        second = record_lead(tx, email=dotted, source='alert:visitor')
    assert first == second


def test_a_member_is_not_a_lead(addresses, make_person):
    person = make_person(name='LeadMember')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=person['id'])).fetchone()['email']
    addresses.keep(email)
    with api_tx() as tx:
        assert record_lead(tx, email=email, source='tool:game-us') is None
        n = tx.execute('SELECT count(*) AS n FROM lead WHERE email = %(e)s',
                       dict(e=email.lower())).fetchone()['n']
    assert n == 0


def test_consent_needs_its_wording(addresses):
    with pytest.raises(ValueError, match='consent_wording_required'):
        with api_tx() as tx:
            record_lead(tx, email=addresses.new(), source='event:sukkot-2027',
                        marketing_consent=True)


def test_a_later_unticked_box_never_withdraws_consent(addresses):
    email = addresses.new()
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source='event:sukkot-2027',
                              marketing_consent=True, consent_wording='rsvp-2026-11')
        record_lead(tx, email=email, source='event:sukkot-2027')
    row = _lead(lead_id)
    assert row['marketing_consent'] is True
    assert row['consent_wording'] == 'rsvp-2026-11'
    assert row['consented_at'] is not None


def test_a_fresh_tick_after_unsubscribing_waits_for_a_new_confirm_link(addresses):
    # Anyone can type an address into a form and tick the box, so a tick
    # after an unsubscribe counts only once the address itself taps a
    # confirm link issued after that tick.
    email = addresses.new()
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source='alert:visitor',
                              marketing_consent=True, consent_wording='alert-2026-11')
        old_token = issue_confirm_token(tx, lead_id)
        confirm_by_token(tx, old_token)
        tx.execute('UPDATE lead SET unsubscribed_at = NOW() WHERE id = %(i)s', dict(i=lead_id))
    with api_tx() as tx:
        record_lead(tx, email=email, source='alert:visitor',
                    marketing_consent=True, consent_wording='alert-2026-12')
        assert lead_unsubscribed(tx, lead_id) is True
        assert confirm_by_token(tx, old_token) == lead_id
        assert lead_unsubscribed(tx, lead_id) is True, 'a link issued before the tick proves nothing'
    with api_tx() as tx:
        new_token = issue_confirm_token(tx, lead_id)
    with api_tx() as tx:
        assert confirm_by_token(tx, new_token) == lead_id
        assert lead_unsubscribed(tx, lead_id) is False
    row = _lead(lead_id)
    assert row['consent_wording'] == 'alert-2026-12'
    assert row['consent_pending_wording'] is None and row['consent_pending_at'] is None


@pytest.mark.parametrize('email,source,error', [
    ('someone@example.org', 'utm:facebook/event', 'bad_source'),
    ('someone@example.org', 'intro', 'bad_source'),
    ('not-an-address', 'tool:game-me', 'bad_email'),
    ('a@b', 'tool:game-me', 'bad_email'),
    ('two@at@example.org', 'tool:game-me', 'bad_email'),
    (None, 'tool:game-me', 'bad_email'),
])
def test_bad_input_is_refused(email, source, error):
    with pytest.raises(ValueError, match=error):
        with api_tx() as tx:
            record_lead(tx, email=email, source=source)


def test_a_confirm_link_confirms_and_works_twice(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='event:sukkot-2027')
        token = issue_confirm_token(tx, lead_id)
    assert len(token) == 32
    with api_tx() as tx:
        assert confirm_by_token(tx, token) == lead_id
        assert confirm_by_token(tx, token) == lead_id
    row = _lead(lead_id)
    assert row['confirmed_at'] is not None and row['confirmed_via'] == 'link'
    assert row['confirm_token_hash'] != token and len(row['confirm_token_hash']) == 64


def test_a_lapsed_forged_or_odd_token_confirms_nothing(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='alert:visitor')
        token = issue_confirm_token(tx, lead_id)
        tx.execute("""UPDATE lead SET confirm_token_expires_at = NOW() - interval '1 minute'
                       WHERE id = %(i)s""", dict(i=lead_id))
    with api_tx() as tx:
        assert confirm_by_token(tx, token) is None
        assert confirm_by_token(tx, secrets.token_urlsafe(24)) is None
        for odd in ('', 'x', None, 42, 'a' * 200):
            assert confirm_by_token(tx, odd) is None
    assert _lead(lead_id)['confirmed_at'] is None


def test_a_code_confirmation_is_recorded_as_otp_and_kept(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='tool:checklist')
        confirm_lead(tx, lead_id, 'otp')
        token = issue_confirm_token(tx, lead_id)
        confirm_by_token(tx, token)
        with pytest.raises(ValueError, match='bad_via'):
            confirm_lead(tx, lead_id, 'carrier-pigeon')
    assert _lead(lead_id)['confirmed_via'] == 'otp'


def test_a_visit_moves_last_seen(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='tool:game-me')
        tx.execute("UPDATE lead SET last_seen_at = NOW() - interval '200 days' WHERE id = %(i)s",
                   dict(i=lead_id))
        touch_lead(tx, lead_id)
        age = tx.execute('SELECT NOW() - last_seen_at AS a FROM lead WHERE id = %(i)s',
                         dict(i=lead_id)).fetchone()['a']
    assert age.total_seconds() < 60


def test_an_unknown_lead_reads_as_unsubscribed():
    with api_tx() as tx:
        assert lead_unsubscribed(tx, -1) is True
