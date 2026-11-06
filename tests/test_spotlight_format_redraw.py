"""Format-only redraw of an approved member card (TEC-2113,
docs/plans/2026-11-06-spotlight-format-redraw.md).

The owner, 6 Nov 2026, on Stewart's approved member-of-the-week card: "redraw
at 4:5, it's already approved, so no need to email him anything, it's just an
aspect ratio fix." The revision and its consent stay, nothing is sent to the
member, and the rows are held out of the publish run until every platform
carries the new artwork.

`_make_eligible` and the session helper are copied from the other Spotlight
test files on purpose: test files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from database import api_tx
from service.spotlight.queue import create_candidate, set_setting, set_status
from service.spotlight.revisions import consent_complete, current_revision, edit_caption, record_consent

H = {'X-Growth-Cron': 'test-cron-secret'}
FUTURE_SLOT = '2031-11-10T12:00:00+00:00'
PAST_SLOT = '2001-01-01T12:00:00+00:00'


@pytest.fixture(scope='module', autouse=True)
def redraw_schema(format_redraw_schema):
    """Re-applied per module on top of conftest's session fixture: a
    migration test that re-runs 0044 puts back a claim without the hold."""
    path = Path(__file__).resolve().parent.parent / 'migrations' / '0096_spotlight_format_redraw.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


@pytest.fixture
def storage(monkeypatch):
    """Uploads and public flips are recorded, never sent anywhere."""
    import service.spotlight.storage as st
    calls = dict(put=[], public=[])
    monkeypatch.setattr(st, 'put_card_image',
                        lambda key, data, content_type, public=False: calls['put'].append(key))
    monkeypatch.setattr(st, 'make_public', lambda key: calls['public'].append(key))
    return calls


@pytest.fixture
def approvals():
    with api_tx() as tx:
        set_setting(tx, 'approvals_enabled', 'true')
        set_setting(tx, 'invites_enabled', 'true')
    yield
    with api_tx() as tx:
        set_setting(tx, 'approvals_enabled', 'false')


def _image(size, colour, fmt):
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, fmt, quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _make_eligible(make_person, name):
    p = make_person(name=name, gender='Man')
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL,
                   email = %(e)s
             WHERE id = %(id)s""", dict(id=p['id'], e=f'redraw-{p["id"]}@ahavah-test.invalid'))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _admin(make_person):
    admin = make_person(name='RedrawAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=admin['id']))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))
    return {'Authorization': f'Bearer {tok}'}, email


def _rows(rk):
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT id::text AS id, platform, status, scheduled_for, image_key, image_url, image_sha256,
                      current_revision_id, format_redraw_requested_at
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()


def _draw_square(client, rk):
    """The card as it was first drawn and approved: square, as a PNG."""
    png = _image((1080, 1080), 'white', 'PNG')
    for row in _rows(rk):
        r = client.post(f'/admin/growth/queue/{rk}/image', json={'platform': row['platform'], 'png_base64': png},
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _live_caption(person_id, kind):
    """The caption the card's own builder makes from the member's profile,
    as the welcome and member-of-the-week routes write it."""
    from service.api.admin.spotlight_routes import _member_of_week_caption, _welcome_caption
    with api_tx('read committed') as tx:
        info = tx.execute(
            """SELECT split_part(name, ' ', 1) AS first_name,
                      date_part('year', age(date_of_birth))::int AS age,
                      COALESCE(country, location_short_friendly) AS country
                 FROM person WHERE id = %(p)s""", dict(p=person_id)).fetchone()
    if kind == 'welcome':
        return _welcome_caption(info['first_name'], info['country'])
    return _member_of_week_caption(info['first_name'], info['age'], info['country'])


def _approved_card(client, make_person, A, *, kind='member_of_week', slot=FUTURE_SLOT, schedule=True,
                   caption=None):
    """A member card drawn, consented to and (by default) approved onto a
    slot, as Stewart's is."""
    p = _make_eligible(make_person, name=f'Redraw{kind} Surname')
    caption = caption or _live_caption(p['id'], kind)      # never inside an open api_tx
    with api_tx() as tx:
        rk = create_candidate(tx, kind=kind, subject_person_id=p['id'], caption=caption, created_by='t')
    _draw_square(client, rk)
    with api_tx() as tx:
        record_consent(tx, current_revision(tx, rk)['id'], p['id'], 'subject')
        for row in tx.execute("SELECT id FROM publishing_queue WHERE request_key = %(rk)s",
                              dict(rk=rk)).fetchall():
            set_status(tx, row['id'], 'review')
    if schedule:
        for row in _rows(rk):
            r = client.post(f'/admin/growth/queue/{row["id"]}/approve', json={'scheduled_for': slot}, headers=A)
            assert r.status_code == 200, r.get_json()
    return p, rk


def _ask(client, rk, A):
    return client.post(f'/admin/growth/queue/{_rows(rk)[0]["id"]}/format-redraw', json={}, headers=A)


def _upload(client, rk, platform, colour='navy'):
    """What the admin's tick does for a held request: the current renderer's
    card, 4:5 here, through the replace path."""
    return client.post(f'/admin/growth/queue/{rk}/format-redraw/image',
                       json={'platform': platform, 'image_base64': _image((1080, 1350), colour, 'JPEG'),
                             'content_type': 'image/jpeg'},
                       headers=H)


def _redraw(client, rk):
    for platform in ('facebook', 'instagram'):
        r = _upload(client, rk, platform)
        assert r.status_code == 200, r.get_json()


def _sent_to(person_id):
    with api_tx('read committed') as tx:
        mail = tx.execute("SELECT count(*) AS n FROM email_outbox WHERE person_id = %(p)s",
                          dict(p=person_id)).fetchone()['n']
        push = tx.execute("SELECT count(*) AS n FROM push_send_log WHERE person_id = %(p)s",
                          dict(p=person_id)).fetchone()['n']
    return mail, push


def _claimed(rk):
    with api_tx() as tx:
        return [r for r in tx.execute("SELECT * FROM claim_spotlight_posts(50)").fetchall()
                if r['request_key'] == rk]


# ---------------------------------------------------------------------------
# The redraw itself
# ---------------------------------------------------------------------------

def test_redraw_keeps_the_revision_its_consent_and_its_slot(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A)
    before = _rows(rk)
    with api_tx('read committed') as tx:
        rev = current_revision(tx, rk)
        consent = tx.execute("SELECT * FROM spotlight_revision_consent WHERE revision_id = %(r)s",
                             dict(r=rev['id'])).fetchall()

    r = _ask(client, rk, A)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['held'] == 2
    held = _rows(rk)
    assert all(row['format_redraw_requested_at'] is not None for row in held)
    assert [row['status'] for row in held] == ['scheduled', 'scheduled']
    # The old artwork stays on the rows until the new artwork lands.
    assert [row['image_key'] for row in held] == [row['image_key'] for row in before]

    _redraw(client, rk)
    after = _rows(rk)
    with api_tx('read committed') as tx:
        rev_after = current_revision(tx, rk)
        consent_after = tx.execute("SELECT * FROM spotlight_revision_consent WHERE revision_id = %(r)s",
                                   dict(r=rev['id'])).fetchall()
        assert consent_complete(tx, rev['id'])
    assert rev_after['id'] == rev['id'] and rev_after['revision'] == rev['revision']
    assert rev_after['caption'] == rev['caption'] and rev_after['photo_uuid'] == rev['photo_uuid']
    assert consent_after == consent
    assert [row['status'] for row in after] == ['scheduled', 'scheduled']
    assert [row['scheduled_for'] for row in after] == [row['scheduled_for'] for row in before]
    assert all(row['format_redraw_requested_at'] is None for row in after)
    assert all(row['current_revision_id'] == rev['id'] for row in after)
    new_sha = {row['image_sha256'] for row in after}
    assert len(new_sha) == 1 and new_sha != {row['image_sha256'] for row in before}
    assert all(row['image_key'].endswith('.jpg') for row in after)
    # The revision now names the new render, pinned to the facebook row.
    assert rev_after['asset_hash'] == after[0]['image_sha256']
    assert rev_after['image_key'] == after[0]['image_key']
    # The rows are scheduled, so the new objects are public before the hold
    # comes off.
    assert set(storage['public']) >= {row['image_key'] for row in after}


def test_redraw_queues_no_email_and_no_push(client, make_person, storage, approvals, monkeypatch):
    import service.api.admin.spotlight_routes as sr

    def refuse(*a, **kw):
        raise AssertionError('the redraw must not queue the card-ready email')

    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A)
    before = _sent_to(p['id'])
    monkeypatch.setattr(sr, '_enqueue_card_ready', refuse)
    monkeypatch.setattr(sr, '_enqueue_card_ready_on_render', refuse)
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    assert _sent_to(p['id']) == before


def test_old_artwork_is_queued_for_deletion(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    old_keys = [row['image_key'] for row in _rows(rk)]
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    with api_tx('read committed') as tx:
        queued = {r['target'] for r in tx.execute(
            "SELECT target FROM cleanup_job WHERE target = ANY(%(k)s) AND state = 'pending'",
            dict(k=old_keys)).fetchall()}
    assert queued == set(old_keys)


def test_a_key_a_published_row_still_uses_is_not_deleted(client, make_person, storage, approvals):
    """The cleanup guard is `is_referenced`: anything still naming the old
    object keeps it. Simulated by a published row of another request that
    happens to name the same key."""
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A)
    old_ig = _rows(rk)[1]['image_key']
    with api_tx() as tx:
        other = create_candidate(tx, kind='welcome', subject_person_id=p['id'], caption='c', created_by='t')
        tx.execute("""UPDATE publishing_queue SET status = 'published', image_key = %(k)s
                       WHERE request_key = %(rk)s AND platform = 'instagram'""", dict(k=old_ig, rk=other))
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM cleanup_job WHERE target = %(k)s AND state = 'pending'",
                          dict(k=old_ig)).fetchone() is None


def test_asking_twice_changes_nothing(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    assert _ask(client, rk, A).get_json()['already'] is False
    first = [row['format_redraw_requested_at'] for row in _rows(rk)]
    r = _ask(client, rk, A)
    assert r.status_code == 200 and r.get_json()['already'] is True
    assert [row['format_redraw_requested_at'] for row in _rows(rk)] == first


def test_a_card_still_in_review_is_redrawn_and_stays_in_review(client, make_person, storage, approvals):
    """Approved by the member, not yet by the admin: nothing is made public
    (approval does that), and the row stays where it was."""
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, schedule=False)
    storage['public'].clear()
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    rows = _rows(rk)
    assert [row['status'] for row in rows] == ['review', 'review']
    assert all(row['format_redraw_requested_at'] is None for row in rows)
    assert storage['public'] == []


# ---------------------------------------------------------------------------
# Never publish the old artwork, or no artwork, while the redraw is pending
# ---------------------------------------------------------------------------

def test_a_held_row_is_never_claimed_even_past_its_slot(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, slot=PAST_SLOT)
    assert _ask(client, rk, A).status_code == 200

    assert _claimed(rk) == []                       # old square artwork on both rows
    assert _upload(client, rk, 'facebook').status_code == 200
    assert _claimed(rk) == []                       # one platform redrawn, the other not
    rows = _rows(rk)
    assert rows[0]['image_sha256'] != rows[1]['image_sha256']
    assert all(row['image_key'] for row in rows)    # never without artwork

    assert _upload(client, rk, 'instagram').status_code == 200
    claimed = sorted(_claimed(rk), key=lambda r: r['platform'])
    assert [r['platform'] for r in claimed] == ['facebook', 'instagram']
    assert len({r['image_sha256'] for r in claimed}) == 1
    assert all(r['image_key'].endswith('.jpg') for r in claimed)


def test_a_redraw_finishing_after_the_slot_is_audited_as_late(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, slot=PAST_SLOT)
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    with api_tx('read committed') as tx:
        done = tx.execute(
            """SELECT actor_email, metadata FROM admin_audit_log
                WHERE action = 'growth.queue.format_redraw.done' AND metadata->>'request_key' = %(rk)s""",
            dict(rk=rk)).fetchone()
    assert done['actor_email'] == 'cron'
    assert done['metadata']['late'] is True
    assert [row['scheduled_for'] for row in _rows(rk)] == [datetime(2001, 1, 1, 12, tzinfo=timezone.utc)] * 2


def test_a_square_redraw_is_refused_and_the_card_stays_held(client, make_person, storage, approvals):
    """Asked for before the 4:5 renderer is live: the tick still draws
    square, and that must not clear the hold and post the square card."""
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, slot=PAST_SLOT)
    before = _rows(rk)
    assert _ask(client, rk, A).status_code == 200
    for platform in ('facebook', 'instagram'):
        r = client.post(f'/admin/growth/queue/{rk}/format-redraw/image',
                        json={'platform': platform, 'image_base64': _image((1080, 1080), 'navy', 'JPEG'),
                              'content_type': 'image/jpeg'}, headers=H)
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_image', 'reason': 'bad_dimensions'}
    rows = _rows(rk)
    assert all(row['format_redraw_requested_at'] is not None for row in rows)
    assert [row['image_key'] for row in rows] == [row['image_key'] for row in before]
    assert storage['put'] == [k for k in storage['put'] if not k.endswith('.jpg')]   # nothing uploaded
    assert _claimed(rk) == []
    # Once the renderer draws 4:5, the same card goes through.
    _redraw(client, rk)
    assert len(_claimed(rk)) == 2


def test_dispatch_refuses_a_held_row(make_person):
    """Second guard behind the claim filter: a held row that somehow holds a
    lease is refused before any Graph call."""
    from service.spotlight.dispatch import dispatch_check
    from service.spotlight.revisions import attach_render
    p = _make_eligible(make_person, name='RedrawDispatch')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=p['id'], caption='c', created_by='t')
        rev = current_revision(tx, rk)
        attach_render(tx, rev['id'], 'h', 'k', 'https://cdn/k.png')
        record_consent(tx, rev['id'], p['id'], 'subject')
        row = tx.execute(
            """UPDATE publishing_queue SET status = 'processing', lease_token = 'tok',
                      lease_until = NOW() + interval '5 minutes', format_redraw_requested_at = NOW()
                WHERE request_key = %(rk)s AND platform = 'facebook' RETURNING id""",
            dict(rk=rk)).fetchone()
        assert dispatch_check(tx, row['id'], 'tok') == (False, 'format_redraw_pending')


def test_a_failed_public_flip_keeps_the_hold_and_the_next_tick_finishes(client, make_person, storage,
                                                                        approvals, monkeypatch):
    import service.spotlight.storage as st
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, slot=PAST_SLOT)
    assert _ask(client, rk, A).status_code == 200

    def boom(key):
        raise RuntimeError('spaces down')

    monkeypatch.setattr(st, 'make_public', boom)
    assert _upload(client, rk, 'facebook').status_code == 200
    r = _upload(client, rk, 'instagram')
    assert r.status_code == 503 and r.get_json()['error'] == 'storage_unavailable'
    assert all(row['format_redraw_requested_at'] is not None for row in _rows(rk))
    assert _claimed(rk) == []

    # The next tick draws the same card again. Both rows already carry these
    # bytes, so its first upload is the one that finishes; the tick stops
    # there, and a second upload would find nothing held.
    monkeypatch.setattr(st, 'make_public', lambda key: storage['public'].append(key))
    r = _upload(client, rk, 'facebook')
    assert r.status_code == 200 and r.get_json()['done'] is True
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))
    assert _upload(client, rk, 'instagram').get_json() == {'error': 'no_redraw_pending'}
    assert len(_claimed(rk)) == 2


def test_a_new_revision_clears_the_hold(client, make_person, storage, approvals):
    """A caption edit is new content: it un-renders the rows, and the tick
    draws the new revision through the normal flow, so the hold must not
    outlive it."""
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, schedule=False)
    assert _ask(client, rk, A).status_code == 200
    with api_tx() as tx:
        edit_caption(tx, rk, 'A different caption', 't')
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))
    assert _upload(client, rk, 'facebook').get_json() == {'error': 'no_redraw_pending'}


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('kind', ['roundup', 'brand'])
def test_refused_for_cards_that_are_not_member_cards(client, make_person, kind):
    A, _ = _admin(make_person)
    with api_tx() as tx:
        rk = create_candidate(tx, kind=kind, subject_person_id=None, caption='c', created_by='t')
        tx.execute("UPDATE publishing_queue SET status = 'review' WHERE request_key = %(rk)s", dict(rk=rk))
    try:
        r = _ask(client, rk, A)
        assert r.status_code == 409 and r.get_json() == {'error': 'not_member_card'}
        assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))
    finally:
        # An undrawn roundup would sit in the tick's render listing, which
        # other files in the same run read with a limit.
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET status = 'cancelled' WHERE request_key = %(rk)s",
                       dict(rk=rk))


@pytest.mark.parametrize('status', ['published', 'cancelled'])
def test_refused_once_a_row_is_published_or_cancelled(client, make_person, storage, approvals, status):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = %(s)s WHERE request_key = %(rk)s AND platform = 'instagram'",
                   dict(s=status, rk=rk))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'terminal'}
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))


def test_refused_while_a_row_is_being_published(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'processing' WHERE request_key = %(rk)s AND platform = 'facebook'",
                   dict(rk=rk))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'bad_status'}


def test_refused_when_the_member_has_not_approved_the_revision(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    p = _make_eligible(make_person, name='RedrawNoConsent')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=p['id'], caption='c', created_by='t')
    _draw_square(client, rk)
    # Still waiting for the member.
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'bad_status'}
    # In review without consent (an operator move, never the normal flow).
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'review' WHERE request_key = %(rk)s", dict(rk=rk))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'not_approved'}
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))


def test_refused_after_the_member_withdrew(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET cancellation_requested_at = NOW() WHERE request_key = %(rk)s",
                   dict(rk=rk))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'withdrawn'}


def test_the_request_needs_an_admin(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    r = client.post(f'/admin/growth/queue/{_rows(rk)[0]["id"]}/format-redraw', json={}, headers=H)
    assert r.status_code in (400, 401, 403)
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))


def test_the_replace_path_is_only_for_a_held_request(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    before = _rows(rk)
    r = _upload(client, rk, 'facebook')
    assert r.status_code == 409 and r.get_json() == {'error': 'no_redraw_pending'}
    assert _rows(rk) == before
    # The ordinary upload still refuses a scheduled row, as it always has.
    r = client.post(f'/admin/growth/queue/{rk}/image',
                    json={'platform': 'facebook', 'image_base64': _image((1080, 1350), 'red', 'JPEG'),
                          'content_type': 'image/jpeg'}, headers=H)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Listing and audit
# ---------------------------------------------------------------------------

def test_the_tick_lists_held_rows_with_what_it_needs_to_draw(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A)
    assert _ask(client, rk, A).status_code == 200
    rows = [r for r in client.get('/admin/growth/queue?format_redraw=1', headers=H).get_json()
            if r['request_key'] == rk]
    assert sorted(r['platform'] for r in rows) == ['facebook', 'instagram']
    assert all(r['format_redraw_pending'] is True for r in rows)
    assert all(r['subject']['person_id'] == p['id'] and r['subject']['photo_url'] for r in rows)
    _redraw(client, rk)
    assert not [r for r in client.get('/admin/growth/queue?format_redraw=1', headers=H).get_json()
                if r['request_key'] == rk]


def test_the_request_and_the_redraw_are_audited(client, make_person, storage, approvals):
    A, admin_email = _admin(make_person)
    _, rk = _approved_card(client, make_person, A)
    old = {row['platform']: row['image_key'] for row in _rows(rk)}
    revision_id = _rows(rk)[0]['current_revision_id']
    assert _ask(client, rk, A).status_code == 200
    _redraw(client, rk)
    new = {row['platform']: row['image_key'] for row in _rows(rk)}
    with api_tx('read committed') as tx:
        audits = tx.execute(
            """SELECT action, actor_email, metadata, created_at FROM admin_audit_log
                WHERE action LIKE 'growth.queue.format_redraw%%' AND metadata->>'request_key' = %(rk)s
                ORDER BY created_at, id""",
            dict(rk=rk)).fetchall()
    asked = [a for a in audits if a['action'] == 'growth.queue.format_redraw']
    assert len(asked) == 1
    assert asked[0]['actor_email'] == admin_email and asked[0]['created_at'] is not None
    assert asked[0]['metadata']['old_keys'] == old
    assert asked[0]['metadata']['revision_id'] == revision_id
    images = {a['metadata']['platform']: (a['metadata']['old_key'], a['metadata']['new_key'])
              for a in audits if a['action'] == 'growth.queue.format_redraw.image'}
    assert images == {p: (old[p], new[p]) for p in ('facebook', 'instagram')}
    done = [a for a in audits if a['action'] == 'growth.queue.format_redraw.done']
    assert len(done) == 1 and done[0]['actor_email'] == 'cron'
    assert done[0]['metadata']['new_keys'] == new
    assert done[0]['metadata']['previous_revision_key'] == old['facebook']
    assert done[0]['metadata']['revision_id'] == revision_id
    assert done[0]['metadata']['late'] is False


# ---------------------------------------------------------------------------
# The redraw draws what the member approved (review, 6 Nov 2026)
# ---------------------------------------------------------------------------

def _refusals(rk):
    with api_tx('read committed') as tx:
        return [r['metadata'] for r in tx.execute(
            """SELECT metadata FROM admin_audit_log
                WHERE action = 'growth.queue.format_redraw.refused' AND metadata->>'request_key' = %(rk)s""",
            dict(rk=rk)).fetchall()]


@pytest.mark.parametrize('kind', ['member_of_week', 'welcome'])
def test_refused_when_the_name_changed_since_approval(client, make_person, storage, approvals, kind):
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A, kind=kind)
    with api_tx() as tx:
        tx.execute("UPDATE person SET name = 'Renamed Person' WHERE id = %(p)s", dict(p=p['id']))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'subject_changed', 'field': 'name'}
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))
    assert [m['field'] for m in _refusals(rk)] == ['name']


@pytest.mark.parametrize('kind', ['member_of_week', 'welcome'])
def test_refused_when_a_birthday_passed_since_approval(client, make_person, storage, approvals, kind):
    """Approved three days ago, at 29; the birthday was yesterday. The card
    would now print 30, which the member never saw."""
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A, kind=kind)
    revision_id = _rows(rk)[0]['current_revision_id']     # never inside an open api_tx
    with api_tx() as tx:
        tx.execute("""UPDATE person SET date_of_birth = (CURRENT_DATE - interval '30 years' - interval '1 day')::date
                       WHERE id = %(p)s""", dict(p=p['id']))
        tx.execute("""UPDATE spotlight_revision_consent SET approved_at = NOW() - interval '3 days'
                       WHERE revision_id = %(r)s""", dict(r=revision_id))
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json() == {'error': 'subject_changed', 'field': 'age'}
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))
    assert [m['field'] for m in _refusals(rk)] == ['age']


def test_refused_when_the_caption_cannot_say_what_the_card_showed(client, make_person, storage, approvals):
    A, _ = _admin(make_person)
    _, rk = _approved_card(client, make_person, A, caption='A week of good company. More here.')
    r = _ask(client, rk, A)
    assert r.status_code == 409 and r.get_json()['error'] == 'subject_changed'
    assert r.get_json()['field'] in ('name', 'caption')
    assert all(row['format_redraw_requested_at'] is None for row in _rows(rk))


def test_the_redraw_draws_the_frozen_name_and_age_not_the_live_profile(client, make_person, storage,
                                                                         approvals):
    """Checked and frozen when asked for: a profile change before the tick
    does not reach the card."""
    A, _ = _admin(make_person)
    p, rk = _approved_card(client, make_person, A)
    before = [r for r in client.get('/admin/growth/queue', headers=H).get_json() if r['request_key'] == rk][0]
    assert _ask(client, rk, A).status_code == 200
    with api_tx() as tx:
        tx.execute("""UPDATE person SET name = 'Renamed Person', country = 'FR',
                             date_of_birth = (CURRENT_DATE - interval '50 years')::date
                       WHERE id = %(p)s""", dict(p=p['id']))
    rows = [r for r in client.get('/admin/growth/queue?format_redraw=1', headers=H).get_json()
            if r['request_key'] == rk]
    assert len(rows) == 2
    for row in rows:
        assert row['subject']['first_name'] == before['subject']['first_name']
        assert row['subject']['age'] == before['subject']['age']
        assert row['subject']['country'] == before['subject']['country']
    _redraw(client, rk)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM publishing_queue WHERE request_key = %(rk)s "
                          "AND format_redraw_subject IS NOT NULL", dict(rk=rk)).fetchone()['n'] == 0
