"""Leads go 12 months after the last visit, or with the account (TEC-1845).

The specs promise: "Rows are deleted 12 months after the last visit, or on
request." A lead linked at sign-up goes with the person row; one that never
was (unconfirmed, or from a flow the member used before joining) is found
by its normalised address, however it was typed. Both hard deletes, the
deletion cron and the admin's, do it. An address nobody confirmed goes a
day after its confirm link lapsed: it has no use once that link is dead.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Optional
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import outbox
from service.cron.leadretention import purge_stale_leads
from service.cron.pendingdeletion import hard_delete_expired_once

pytestmark = pytest.mark.usefixtures('growth_schema')


def _insert_lead(tx, email: str, source: str, *, person_id=None, days_since_visit: int = 0,
                 days_since_created: int = 0, confirmed: bool = False,
                 normalized: Optional[str] = None) -> int:
    return tx.execute(
        """INSERT INTO lead (email, normalized_email, source, person_id, last_seen_at,
                             created_at, confirmed_at)
           VALUES (%(e)s, %(ne)s, %(s)s, %(p)s, NOW() - make_interval(days => %(d)s),
                   NOW() - make_interval(days => %(c)s), CASE WHEN %(conf)s THEN NOW() END)
           RETURNING id""",
        dict(e=email.lower(), ne=normalized or email.lower(), s=source, p=person_id,
             d=days_since_visit, c=days_since_created, conf=confirmed)).fetchone()['id']


def _exists(lead_id: int) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT 1 FROM lead WHERE id = %(i)s', dict(i=lead_id)).fetchone() is not None


def test_a_lead_unseen_for_a_year_goes_with_its_mail_and_a_recent_one_stays():
    stale_email = f'stale-{uuid4().hex[:10]}@ahavah-test.invalid'
    fresh_email = f'fresh-{uuid4().hex[:10]}@ahavah-test.invalid'
    with api_tx() as tx:
        stale = _insert_lead(tx, stale_email, 'alert:visitor', days_since_visit=366)
        fresh = _insert_lead(tx, fresh_email, 'alert:visitor', days_since_visit=364)
        mail = outbox.enqueue_for_lead(tx, campaign='test-retention', campaign_id='r1',
                                       lead_id=stale, email=stale_email, subject='s',
                                       html='<p>h</p>', from_addr=None)
    try:
        with api_tx() as tx:
            assert purge_stale_leads(tx) >= 1
        assert not _exists(stale)
        assert _exists(fresh)
        with api_tx('read committed') as tx:
            assert tx.execute('SELECT 1 FROM email_outbox WHERE id = %(i)s',
                              dict(i=mail)).fetchone() is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)',
                       dict(e=[stale_email, fresh_email]))


def test_an_address_never_confirmed_goes_once_its_link_has_lapsed():
    # Seen today, so only the unconfirmed rule can take it.
    lapsed_email = f'unproved-{uuid4().hex[:10]}@ahavah-test.invalid'
    proved_email = f'proved-{uuid4().hex[:10]}@ahavah-test.invalid'
    with api_tx() as tx:
        lapsed = _insert_lead(tx, lapsed_email, 'event:sukkot-2027', days_since_created=9)
        proved = _insert_lead(tx, proved_email, 'event:sukkot-2027', days_since_created=9,
                              confirmed=True)
    try:
        with api_tx() as tx:
            purge_stale_leads(tx)
        assert not _exists(lapsed)
        assert _exists(proved)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)',
                       dict(e=[lapsed_email, proved_email]))


def _email_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=person_id)).fetchone()['email']


def test_the_deletion_cron_deletes_a_leavers_leads(make_person):
    p = make_person(name='LeadLeaver', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        linked = _insert_lead(tx, email, 'tool:game-me', person_id=p['id'])
        unlinked = _insert_lead(tx, email, 'event:sukkot-2027')
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))
    asyncio.run(hard_delete_expired_once())
    assert not _exists(linked)
    assert not _exists(unlinked)


def test_a_leavers_lead_typed_another_way_goes_too(make_person):
    name = f'leaver{uuid4().hex[:8]}'
    p = make_person(name='LeadLeaverGmail', gender='Woman', email=f'{name}@gmail.com')
    variant = f'{name[:3]}.{name[3:]}+tools@gmail.com'
    with api_tx() as tx:
        unlinked = _insert_lead(tx, variant, 'tool:game-me', normalized=f'{name}@gmail.com')
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))
    asyncio.run(hard_delete_expired_once())
    assert not _exists(unlinked)


def _admin_headers(make_person) -> dict:
    admin = make_person(name='LeadAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def test_the_admin_hard_delete_deletes_the_members_leads(make_person, client):
    headers = _admin_headers(make_person)
    p = make_person(name='LeadAdminDeleted', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        linked = _insert_lead(tx, email, 'tool:game-us', person_id=p['id'])
        unlinked = _insert_lead(tx, email, 'alert:visitor')
    r = client.delete(f"/admin/users/{p['uuid']}",
                      json={'confirm_email': email, 'reason': 'test'}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert not _exists(linked)
    assert not _exists(unlinked)


def _invitation_record(tx, email: str) -> None:
    """The once-per-address record of the invitation to join (0076)."""
    from antiabuse.antispam.signupemail import normalize_email
    tx.execute('INSERT INTO lead_join_invite (normalized_email) VALUES (%(ne)s) ON CONFLICT DO NOTHING',
               dict(ne=normalize_email(email)))


def _invitation_held(email: str) -> bool:
    from antiabuse.antispam.signupemail import normalize_email
    with api_tx('read committed') as tx:
        return tx.execute('SELECT 1 FROM lead_join_invite WHERE normalized_email = %(ne)s',
                          dict(ne=normalize_email(email))).fetchone() is not None


def test_the_deletion_cron_deletes_the_invitation_record_with_the_leads(make_person):
    """The record goes in the same transaction as the address's lead rows,
    as every other table keyed only on the address does, not in the next
    day's retention sweep."""
    p = make_person(name='InviteLeaver', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        lead = _insert_lead(tx, email, 'event:sukkot-2027')
        _invitation_record(tx, email)
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))
    asyncio.run(hard_delete_expired_once())
    assert not _exists(lead)
    assert not _invitation_held(email)


def test_the_admin_hard_delete_deletes_the_invitation_record(make_person, client):
    headers = _admin_headers(make_person)
    p = make_person(name='InviteAdminDeleted', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        lead = _insert_lead(tx, email, 'event:sukkot-2027')
        _invitation_record(tx, email)
    r = client.delete(f"/admin/users/{p['uuid']}",
                      json={'confirm_email': email, 'reason': 'test'}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert not _exists(lead)
    assert not _invitation_held(email)
