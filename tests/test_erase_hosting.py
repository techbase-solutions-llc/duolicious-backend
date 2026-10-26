"""The erase code covers organisers (TEC-1845, in-app plan release 4,
section 5): "delete everything under this email" and an account's deletion
take the organiser rows of the address, with their gatherings, links and
the RSVPs on them. A published gathering still to come is cancelled first,
so its confirmed guests hear, and its posts not yet out are cancelled.
Ahavah's own organiser (kind 'ahavah') is never erased by address.

The admin's hard delete and the deletion cron run
service.events.retention.erase_hosting."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from database import api_tx
from service.events import retention

pytestmark = pytest.mark.usefixtures('events_schema', 'join_invite_schema', 'events_live', 'no_limits')
NOW = datetime.now(timezone.utc)


def _one(sql, **params):
    with api_tx('read committed') as tx:
        row = tx.execute(sql, params).fetchone()
    return dict(row) if row else None


def _organiser_at(address: str, kind: str = 'fellowship_leader') -> int:
    from service.events.organisers import issue_link
    with api_tx() as tx:
        oid = tx.execute(
            """INSERT INTO organiser (name, kind, email, normalized_email, verified_at, approved_at)
               VALUES ('Grace Fellowship', %(k)s, %(e)s, %(e)s, NOW(), NOW()) RETURNING id""",
            dict(k=kind, e=address)).fetchone()['id']
        issue_link(tx, oid)
    return oid


@pytest.fixture
def host_address():
    made: list[str] = []

    def _make() -> str:
        address = f'host-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(address)
        return address

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM organiser WHERE normalized_email = ANY(%(e)s)', dict(e=made))


def _erase(nes):
    with api_tx() as tx:
        return retention.erase_hosting(tx, nes)


def test_erase_takes_the_organiser_its_gatherings_links_and_their_rsvps(published, confirmed_guest,
                                                                        host_address, organiser):
    address = host_address()
    oid = _organiser_at(address)
    o = dict(id=oid)
    ended = published(o, starts_at=NOW - timedelta(days=5))
    draft = published(o, status='draft', published_at=None)
    guest = confirmed_guest(ended)
    someone_else = organiser()
    theirs = published(someone_else)
    their_guest = confirmed_guest(theirs)
    _erase([address])
    assert _one('SELECT 1 FROM organiser WHERE id = %(i)s', i=oid) is None
    assert _one('SELECT 1 FROM organiser_link WHERE organiser_id = %(i)s', i=oid) is None
    for slug in (ended, draft):
        assert _one('SELECT 1 FROM event WHERE slug = %(s)s', s=slug) is None
    assert _one('SELECT 1 FROM event_rsvp WHERE id = %(i)s', i=guest['id']) is None
    # Nobody else's.
    assert _one('SELECT 1 FROM event WHERE slug = %(s)s', s=theirs) is not None
    assert _one('SELECT 1 FROM event_rsvp WHERE id = %(i)s', i=their_guest['id']) is not None


def test_a_gathering_still_to_come_is_cancelled_first_so_its_guests_hear(published, confirmed_guest,
                                                                         host_address, outbox_rows):
    address = host_address()
    o = dict(id=_organiser_at(address))
    slug = published(o)
    guest = confirmed_guest(slug)
    _erase([address])
    rows = [r for r in outbox_rows('event_cancelled') if r['email'] == guest['email']]
    assert len(rows) == 1
    assert _one('SELECT 1 FROM event WHERE slug = %(s)s', s=slug) is None


def test_an_ended_or_draft_gathering_sends_no_cancellation(published, confirmed_guest, host_address,
                                                           outbox_rows):
    address = host_address()
    o = dict(id=_organiser_at(address))
    ended = published(o, starts_at=NOW - timedelta(days=5))
    guest = confirmed_guest(ended)
    _erase([address])
    assert not [r for r in outbox_rows('event_cancelled') if r['email'] == guest['email']]


def test_posts_not_yet_out_are_cancelled(published, host_address, monkeypatch):
    calls: list[str] = []
    import service.spotlight.growthposts as gp
    monkeypatch.setattr(gp, 'cancel_event_posts', lambda tx, slug: calls.append(slug) or 0)
    address = host_address()
    o = dict(id=_organiser_at(address))
    slugs = {published(o), published(o, starts_at=NOW - timedelta(days=3))}
    _erase([address])
    assert set(calls) == slugs


def test_covers_are_handed_back_for_deletion_after_the_commit(published, host_address):
    address = host_address()
    o = dict(id=_organiser_at(address))
    published(o, cover_key='event-covers/test-cover.jpg')
    assert _erase([address]) == ['event-covers/test-cover.jpg']


def test_ahavahs_own_organiser_is_never_erased_by_address(published, host_address):
    address = host_address()
    oid = _organiser_at(address, kind='ahavah')
    slug = published(dict(id=oid))
    _erase([address])
    assert _one('SELECT 1 FROM organiser WHERE id = %(i)s', i=oid) is not None
    assert _one("SELECT status FROM event WHERE slug = %(s)s", s=slug)['status'] == 'published'


def test_the_address_is_matched_normalised_and_an_empty_list_erases_nothing(published, host_address,
                                                                           organiser):
    other = organiser()
    published(other)
    assert _erase([]) == []
    assert _one('SELECT 1 FROM organiser WHERE id = %(i)s', i=other['id']) is not None


def _admin_headers(make_person, sign_in):
    admin = make_person(name='EraseAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=admin['id']))
    return sign_in(admin)


def test_an_admins_hard_delete_erases_the_members_hosting(client, make_person, sign_in, published,
                                                          host_address):
    address = host_address()
    p = make_person(name='Hosting Member', email=address)
    oid = _organiser_at(address)
    slug = published(dict(id=oid))
    r = client.delete(f"/admin/users/{p['uuid']}", json={'confirm_email': address, 'reason': 'test'},
                      headers=_admin_headers(make_person, sign_in))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _one('SELECT 1 FROM organiser WHERE id = %(i)s', i=oid) is None
    assert _one('SELECT 1 FROM event WHERE slug = %(s)s', s=slug) is None


def test_the_deletion_cron_erases_the_members_hosting(make_person, published, host_address):
    from service.cron.pendingdeletion import hard_delete_expired_once
    address = host_address()
    p = make_person(name='Leaving Host', email=address)
    oid = _organiser_at(address)
    published(dict(id=oid))
    with api_tx() as tx:
        tx.execute("""UPDATE person SET activated = FALSE, deletion_requested_at = NOW() - INTERVAL '8 days',
                             sign_in_time = NOW() - INTERVAL '9 days' WHERE id = %(p)s""", dict(p=p['id']))
    # Its own loop, never set as the current one: asyncio.run would leave
    # no current loop behind, and later modules that ask for one would fail.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(hard_delete_expired_once())
    finally:
        loop.close()
    assert _one('SELECT 1 FROM person WHERE id = %(i)s', i=p['id']) is None
    assert _one('SELECT 1 FROM organiser WHERE id = %(i)s', i=oid) is None


def test_every_deletion_path_runs_the_same_erase():
    root = Path(__file__).resolve().parent.parent
    for path in ('service/cron/pendingdeletion/__init__.py', 'service/api/admin/users_action_routes.py',
                 'service/your_ahavah/__init__.py'):
        assert 'erase_hosting' in (root / path).read_text(encoding='utf-8'), path
