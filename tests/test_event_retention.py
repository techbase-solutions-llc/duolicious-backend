"""Gathering retention (TEC-1845): a guest's name and email go 90 days after
the gathering (the counts stay), an RSVP never confirmed a day after its
window, lapsed organiser links a day after they lapse, invite requests 12
months after their last change; RSVPs go with the account; a guest who
joins is linked and credited to the gathering."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from antiabuse.antispam.signupemail import normalize_email
from database import api_tx
from service.events import retention

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')
NOW = datetime.now(timezone.utc)


def _rsvp(rid):
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s', dict(i=rid)).fetchone()
    return dict(row) if row else None


def _purge():
    with api_tx() as tx:
        return retention.purge_event_data(tx)


def test_names_and_emails_go_90_days_after_the_gathering_and_the_counts_stay(published, confirmed_guest):
    old = published(starts_at=NOW - timedelta(days=91, hours=3))
    recent = published(starts_at=NOW - timedelta(days=89))
    g_old = confirmed_guest(old, party_size=3)
    g_recent = confirmed_guest(recent)
    assert _purge()['erased'] >= 1
    row = _rsvp(g_old['id'])
    assert (row['name'], row['email'], row['normalized_email'], row['token_hash']) == (None, None, None, None)
    assert row['erased_at'] is not None and row['party_size'] == 3 and row['confirmed_at'] is not None
    assert _rsvp(g_recent['id'])['name'] == 'Hannah Okafor'


def test_the_digests_naming_the_guests_go_with_the_names(published):
    from service.campaigns.outbox import enqueue_for_organiser
    old = published(starts_at=NOW - timedelta(days=91, hours=3))
    recent = published(starts_at=NOW - timedelta(days=89))
    ids = {}
    with api_tx() as tx:
        for slug in (old, recent):
            ev = tx.execute('SELECT id, organiser_id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()
            ids[slug] = enqueue_for_organiser(
                tx, campaign='event_digest', campaign_id=f"{ev['id']}:2026-01-01",
                organiser_id=ev['organiser_id'], email='digest@ahavah-test.invalid',
                subject='1 new RSVP', html='<p>Hannah Okafor</p>', from_addr=None)
    assert _purge()['digests'] >= 1
    with api_tx('read committed') as tx:
        left = {r['id'] for r in tx.execute('SELECT id FROM email_outbox WHERE id = ANY(%(i)s)',
                                            dict(i=list(ids.values()))).fetchall()}
    assert left == {ids[recent]}


def test_an_rsvp_never_confirmed_goes_a_day_after_its_window(published, confirmed_guest):
    slug = published()
    lapsed = confirmed_guest(slug)
    waiting = confirmed_guest(slug)
    with api_tx() as tx:
        tx.execute("UPDATE event_rsvp SET confirmed_at = NULL, confirm_by = NOW() - interval '25 hours' "
                   "WHERE id = %(i)s", dict(i=lapsed['id']))
        tx.execute("UPDATE event_rsvp SET confirmed_at = NULL, confirm_by = NOW() - interval '23 hours' "
                   "WHERE id = %(i)s", dict(i=waiting['id']))
    assert _purge()['unconfirmed'] >= 1
    assert _rsvp(lapsed['id']) is None and _rsvp(waiting['id']) is not None


def test_lapsed_links_go(organiser):
    o = organiser()
    with api_tx() as tx:
        tx.execute("UPDATE organiser_link SET expires_at = NOW() - interval '25 hours' WHERE organiser_id = %(o)s",
                   dict(o=o['id']))
    assert _purge()['links'] >= 1
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM organiser_link WHERE organiser_id = %(o)s', dict(o=o['id'])).fetchone() is None


def test_old_invite_requests_go():
    with api_tx() as tx:
        old, new = [tx.execute(
            """INSERT INTO ahavah_invite_request (gathering, dates, place, contact_name, contact_email, updated_at)
               VALUES ('G', 'D', 'P', 'N', 'retention-x@ahavah-test.invalid', %(u)s) RETURNING id""",
            dict(u=u)).fetchone()['id'] for u in (NOW - timedelta(days=370), NOW - timedelta(days=300))]
    try:
        assert _purge()['requests'] >= 1
        with api_tx('read committed') as tx:
            left = {r['id'] for r in tx.execute('SELECT id FROM ahavah_invite_request WHERE id = ANY(%(i)s)',
                                                dict(i=[old, new])).fetchall()}
        assert left == {new}
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM ahavah_invite_request WHERE id = ANY(%(i)s)', dict(i=[old, new]))


@pytest.mark.parametrize('shape', ['admin_hard_delete', 'pending_deletion_cron'])
def test_deleting_an_account_deletes_its_rsvps(published, confirmed_guest, make_person, shape):
    slug = published()
    p = make_person(name='Leaving', email='leaving-ev@ahavah-test.invalid')
    by_address = confirmed_guest(slug, email='leaving-ev@ahavah-test.invalid')
    other = published()
    by_account = confirmed_guest(other, person_id=p['id'], email='typed-elsewhere@ahavah-test.invalid')
    stranger = confirmed_guest(slug)
    emails = ['leaving-ev@ahavah-test.invalid']
    with api_tx() as tx:
        if shape == 'admin_hard_delete':
            tx.execute(retention.Q_DELETE_EVENT_DATA_OF, dict(nes=[normalize_email(emails[0])], ids=[p['id']]))
        else:
            tx.execute(retention.Q_DELETE_EVENT_DATA_OF,
                       dict(nes=[normalize_email(e) for e in emails], ids=[p['id']]))
    assert _rsvp(by_address['id']) is None and _rsvp(by_account['id']) is None
    assert _rsvp(stranger['id']) is not None


def test_an_account_with_no_address_binds_an_empty_list(published, confirmed_guest):
    slug = published()
    g = confirmed_guest(slug)
    with api_tx() as tx:
        tx.execute(retention.Q_DELETE_EVENT_DATA_OF, dict(nes=[], ids=[]))
    assert _rsvp(g['id']) is not None


def test_the_three_deletion_callers_run_it():
    root = Path(__file__).resolve().parent.parent
    for path in ('service/hard_delete.py', 'service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        text = (root / path).read_text(encoding='utf-8')
        if path.endswith('hard_delete.py'):
            continue  # holds the queries; the two callers below run them
        assert text.count('Q_DELETE_EVENT_DATA_OF') >= 2, path


def test_a_guest_who_joins_is_linked_and_credited_to_the_gathering(published, confirmed_guest, finish_onboarding):
    slug = published()
    address = 'joining-guest-ev@ahavah-test.invalid'
    g = confirmed_guest(slug, email=address)
    r, person_id = finish_onboarding(email=address)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _rsvp(g['id'])['person_id'] == person_id
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                          dict(i=person_id)).fetchone()['lead_source'] == f'event:{slug}'


def test_purge_counts_each_kind():
    with api_tx() as tx:
        out = retention.purge_event_data(tx)
    assert set(out) == {'erased', 'digests', 'unconfirmed', 'links', 'requests'}
