"""Brand posts: Ahavah's own posts from the Claude Design sets (TEC-945).

A brand post is a queue row about nobody. These tests walk it the whole way:
created by the calendar cron, rendered through the existing image route,
approved by an operator, and passed by `dispatch_check` at publish time. The
last of those is the one that matters most. When `brand` was added,
dispatch.py still read `kind != 'roundup'` as "has a subject", so a brand
post would have been approved and then refused as `subject_missing` on every
publish attempt. Creating one proves nothing; dispatching one does.

Session and eligibility helpers are copied from tests/test_spotlight_routes.py
on purpose: test files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image

import service.spotlight.restdays as rd
from database import api_tx
from service.spotlight.dispatch import dispatch_check
from service.spotlight.queue import create_candidate, set_setting
from service.spotlight.revisions import attach_render, current_revision, record_consent

H = {'X-Growth-Cron': 'test-cron-secret'}


def _jpeg(w=1080, h=1350, colour='white') -> str:
    buf = io.BytesIO()
    Image.new('RGB', (w, h), colour).save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _slug() -> str:
    return f'test-{secrets.token_hex(4)}'


def _soon(days: int = 2) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0)


def _session_for(p) -> str:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=p['id']))
    return tok


def _admin_headers(make_person) -> dict:
    p = make_person(name='BrandAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return {'Authorization': f'Bearer {_session_for(p)}'}


def _rows(rk: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id, kind, platform, status, subject_person_id, scheduled_for, caption
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def _cancel(rk: str) -> None:
    """Rows this file schedules are cancelled on the way out: the suite
    shares one database, and a scheduled row left behind is one another
    test's claim could pick up."""
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'cancelled', updated_at = NOW()
                       WHERE request_key = %(rk)s AND status IN ('scheduled', 'processing', 'review', 'awaiting_render', 'awaiting_member')""",
                   dict(rk=rk))


def _create(client, slug=None, caption='A cord of three strands is not quickly broken.',
            when=None, platforms=None):
    body = dict(slug=slug or _slug(), caption=caption,
                scheduled_for=(when or _soon()).isoformat())
    if platforms is not None:
        body['platforms'] = platforms
    return client.post('/admin/growth/brand', json=body, headers=H)


def _render(client, monkeypatch, rk, platforms=('facebook', 'instagram'), w=1080, h=1350):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    for platform in platforms:
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform=platform, image_base64=_jpeg(w, h), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()


@contextmanager
def _publication_on():
    with api_tx() as tx:
        set_setting(tx, 'publication_enabled', 'true')
        set_setting(tx, 'external_access_enabled', 'true')
    try:
        yield
    finally:
        with api_tx() as tx:
            set_setting(tx, 'publication_enabled', 'false')
            set_setting(tx, 'external_access_enabled', 'true')


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def test_a_brand_post_is_created_about_nobody_awaiting_its_artwork(client):
    when = _soon()
    r = _create(client, when=when)
    assert r.status_code == 200, r.get_json()
    rk = r.get_json()['request_key']
    assert rk.startswith('brand:')
    rows = _rows(rk)
    try:
        assert [x['platform'] for x in rows] == ['facebook', 'instagram']
        for x in rows:
            assert x['kind'] == 'brand'
            assert x['subject_person_id'] is None
            assert x['status'] == 'awaiting_render'
            # The calendar's own time rides on every row, so approval can
            # keep it with one click.
            assert x['scheduled_for'] == when
            # A measurable link, like every other post (spec 3.4).
            assert '/s/' in x['caption'] or 'http' in x['caption']
    finally:
        _cancel(rk)


def test_its_artwork_moves_it_to_review_and_nothing_publishes(client, monkeypatch):
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        assert {x['status'] for x in _rows(rk)} == {'review'}
    finally:
        _cancel(rk)


def test_one_platform_only(client):
    rk = _create(client, platforms=['facebook']).get_json()['request_key']
    try:
        assert [x['platform'] for x in _rows(rk)] == ['facebook']
    finally:
        _cancel(rk)


def test_the_same_slug_twice_is_one_post_and_is_not_rewritten(client):
    """A cron that fires twice, or a run retried after a timeout, must not
    make a second post, and must not rewrite a caption the owner may
    already have read."""
    slug = _slug()
    first = _create(client, slug=slug, caption='The first caption.')
    rk = first.get_json()['request_key']
    try:
        again = _create(client, slug=slug, caption='A different caption.')
        assert again.status_code == 200
        assert again.get_json() == dict(request_key=rk, already=True)
        rows = _rows(rk)
        assert len(rows) == 2
        assert all(x['caption'].startswith('The first caption.') for x in rows)
    finally:
        _cancel(rk)


@pytest.mark.parametrize('body,error', [
    (dict(slug='Has Capitals', caption='c'), 'bad_slug'),
    (dict(slug='trailing-', caption='c'), 'bad_slug'),
    (dict(slug='x' * 59, caption='c'), 'bad_slug'),
    (dict(slug='ok-slug', caption='   '), 'bad_caption'),
    (dict(slug='ok-slug', caption='c' * 2001), 'bad_caption'),
    (dict(slug='ok-slug', caption='c', platforms=['threads']), 'bad_platforms'),
    (dict(slug='ok-slug', caption='c', platforms=['facebook', 'facebook']), 'bad_platforms'),
    (dict(slug='ok-slug', caption='c', platforms=[]), 'bad_platforms'),
])
def test_bad_input_is_refused_before_anything_is_written(client, body, error):
    body = dict(body, scheduled_for=_soon().isoformat())
    r = client.post('/admin/growth/brand', json=body, headers=H)
    assert r.status_code == 400 and r.get_json() == dict(error=error)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM publishing_queue WHERE request_key = 'brand:ok-slug'").fetchone() is None


def test_a_slot_is_required(client):
    r = client.post('/admin/growth/brand', json=dict(slug=_slug(), caption='c'), headers=H)
    assert r.status_code == 400 and r.get_json() == dict(error='scheduled_for_required')


def test_the_route_is_not_open_to_the_public(client):
    r = client.post('/admin/growth/brand',
                    json=dict(slug=_slug(), caption='c', scheduled_for=_soon().isoformat()))
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# The owner's calendar, at creation
# ---------------------------------------------------------------------------

def test_a_slot_on_a_rest_day_is_refused(client, monkeypatch):
    sabbath = (datetime.now(rd.BARBADOS) + timedelta(days=3)).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (sabbath,))
    when = datetime.combine(sabbath, datetime.min.time(), rd.BARBADOS).replace(hour=9)
    r = _create(client, when=when)
    assert r.status_code == 409 and r.get_json() == dict(error='slot_unavailable', reason='rest_day')


def test_the_evening_before_a_rest_day_is_refused_too(client, monkeypatch):
    sabbath = (datetime.now(rd.BARBADOS) + timedelta(days=3)).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (sabbath,))
    eve = datetime.combine(sabbath - timedelta(days=1), datetime.min.time(), rd.BARBADOS).replace(hour=18)
    r = _create(client, when=eve)
    assert r.status_code == 409 and r.get_json()['reason'] == 'rest_day'


def test_a_slot_past_the_known_calendar_is_refused(client, monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=1))
    r = _create(client, when=_soon(days=5))
    assert r.status_code == 409 and r.get_json()['reason'] == 'unknown'


def test_a_slot_in_the_past_is_refused(client):
    r = _create(client, when=datetime.now(timezone.utc) - timedelta(hours=1))
    assert r.status_code == 409 and r.get_json()['reason'] == 'past'


# ---------------------------------------------------------------------------
# The artwork: the brand sets are portrait
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('w,h,ok', [(1080, 1350, True), (1080, 1080, False), (1350, 1080, False)])
def test_a_brand_row_takes_portrait_and_nothing_else(client, monkeypatch, w, h, ok):
    """The Claude Design brand sets are 1080 by 1350. The route used to
    accept exactly 1080 by 1080, so every brand card would have come back
    `invalid_image`.

    Square is refused on a brand row even though the route accepts it for
    member cards: square is what the tick's roundup renderer draws, so a
    square image on a brand row is the wrong card (TEC-945 review, the
    "0 new members across 0 countries" finding)."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    rk = _create(client, platforms=['facebook']).get_json()['request_key']
    try:
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform='facebook', image_base64=_jpeg(w, h), content_type='image/jpeg'),
                        headers=H)
        if ok:
            assert r.status_code == 200, r.get_json()
        else:
            assert r.status_code == 400 and r.get_json() == dict(error='invalid_image', reason='bad_dimensions')
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

def _approve(client, headers, qid, **body):
    return client.post(f'/admin/growth/queue/{qid}/approve', json=body, headers=headers)


def test_approval_keeps_the_calendars_slot(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    when = _soon()
    rk = _create(client, when=when).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        qid = _rows(rk)[0]['id']
        r = _approve(client, A, qid)
        assert r.status_code == 200, r.get_json()
        assert _rows(rk)[0]['scheduled_for'] == when
    finally:
        _cancel(rk)


def test_a_late_approval_rolls_forward_instead_of_publishing_at_once(client, monkeypatch, make_person):
    """The calendar said Tuesday, the owner approved on Thursday. Publishing
    the moment the button is pressed could put it out on a Friday evening,
    so the post moves to the next valid slot instead."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET scheduled_for = NOW() - interval '2 days' WHERE request_key = %(rk)s",
                       dict(rk=rk))
        qid = _rows(rk)[0]['id']
        before = datetime.now(timezone.utc)
        r = _approve(client, A, qid)
        assert r.status_code == 200, r.get_json()
        slot = _rows(rk)[0]['scheduled_for']
        assert slot > before
        assert rd.slot_problem(slot, before) is None
    finally:
        _cancel(rk)


def test_an_explicit_slot_on_a_rest_day_is_refused_at_approval(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        sabbath = (datetime.now(rd.BARBADOS) + timedelta(days=4)).date()
        monkeypatch.setattr(rd, 'REST_DAYS', (sabbath,))
        bad = datetime.combine(sabbath, datetime.min.time(), rd.BARBADOS).replace(hour=10)
        r = _approve(client, A, _rows(rk)[0]['id'], scheduled_for=bad.isoformat())
        assert r.status_code == 409 and r.get_json() == dict(error='slot_unavailable', reason='rest_day')
        assert {x['status'] for x in _rows(rk)} == {'review'}, 'a refused approval must not move the row'
    finally:
        _cancel(rk)


def test_other_kinds_keep_the_approval_rule_they_always_had(client, monkeypatch, make_person):
    """Negative control. Only brand posts are held to the calendar at
    approval; any other kind with a stored slot keeps it, past or not,
    exactly as before this change. (Dispatch still refuses them on a rest
    day; see the last test in this file.)"""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    with api_tx() as tx:
        rk = create_candidate(tx, kind='roundup', subject_person_id=None, caption='c', created_by='t')
        rev = current_revision(tx, rk)
        attach_render(tx, rev['id'], 'h', f'spotlight/{rk}/x.jpg', 'https://cdn/x.jpg')
        past = datetime.now(timezone.utc) - timedelta(days=2)
        tx.execute("""UPDATE publishing_queue SET status = 'review', scheduled_for = %(p)s
                       WHERE request_key = %(rk)s""", dict(p=past, rk=rk))
    try:
        qid = _rows(rk)[0]['id']
        r = _approve(client, A, qid)
        assert r.status_code == 200, r.get_json()
        assert abs((_rows(rk)[0]['scheduled_for'] - past).total_seconds()) < 1
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# Dispatch: the check that would have failed
# ---------------------------------------------------------------------------

def _claimed(tx, rk):
    tx.execute("""UPDATE publishing_queue SET status = 'scheduled',
                         scheduled_for = NOW() - interval '1 minute'
                   WHERE request_key = %(rk)s""", dict(rk=rk))
    return [r for r in tx.execute("SELECT * FROM claim_spotlight_posts(10)").fetchall()
            if r['request_key'] == rk]


def test_a_brand_post_passes_dispatch_with_no_subject_and_no_consent(client, monkeypatch):
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        with _publication_on(), api_tx() as tx:
            rows = _claimed(tx, rk)
            assert len(rows) == 2
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (True, '')
    finally:
        _cancel(rk)


def _make_eligible(make_person, name='Elig', gender='Woman'):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL
             WHERE id = %(id)s""", dict(id=p['id']))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _member_card(tx, person_id) -> str:
    """A welcome card that passes every check dispatch makes of a member
    card: rendered, consented to, and its subject still eligible."""
    rk = create_candidate(tx, kind='welcome', subject_person_id=person_id, caption='c', created_by='t')
    rev = current_revision(tx, rk)
    attach_render(tx, rev['id'], 'h', f'spotlight/{rk}/w.jpg', 'https://cdn/w.jpg')
    record_consent(tx, rev['id'], person_id, 'subject')
    return rk


def test_dispatch_refuses_during_a_rest_period_for_every_kind(client, monkeypatch, make_person):
    """The final guarantee, and it holds for member cards as well as brand
    posts: the owner's rule is that nothing promotional goes out on a
    Sabbath. A refusal sends the row back to review with the reason on it.

    The member card is checked before the rest day is switched on, so the
    refusal below is proved to be the rest day and not some other check."""
    brand = _create(client).get_json()['request_key']
    p = _make_eligible(make_person)
    with api_tx() as tx:
        member = _member_card(tx, p['id'])
    try:
        _render(client, monkeypatch, brand)
        with _publication_on(), api_tx() as tx:
            rows = _claimed(tx, brand) + _claimed(tx, member)
            assert {r['kind'] for r in rows} == {'brand', 'welcome'}
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (True, ''), r['kind']
            monkeypatch.setattr(rd, 'REST_DAYS', (datetime.now(rd.BARBADOS).date(),))
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (False, 'rest_day'), r['kind']
    finally:
        _cancel(brand)
        _cancel(member)


def test_a_member_card_still_takes_square(client, monkeypatch):
    """Negative control for the brand-only size rule: the square renderer's
    own cards are unaffected."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    with api_tx() as tx:
        rk = create_candidate(tx, kind='roundup', subject_person_id=None, caption='c', created_by='t')
    try:
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform='facebook', image_base64=_jpeg(1080, 1080), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# Review fix wave (TEC-945)
# ---------------------------------------------------------------------------

def _needs_render_keys(client) -> set:
    r = client.get('/admin/growth/queue?needs_render=1', headers=H)
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    rows = data if isinstance(data, list) else data.get('rows', [])
    return {row['request_key'] for row in rows}


def test_the_render_tick_never_sees_a_brand_post(client):
    """The review's Critical. The tick renders every row it is handed, and
    handed a subject-less row with no tiles it draws a roundup card reading
    "0 new members across 0 countries". A brand post waiting for its artwork
    must not be in the tick's listing at all: its artwork only ever comes
    from the social-queue run."""
    brand = _create(client).get_json()['request_key']
    with api_tx() as tx:
        roundup = create_candidate(tx, kind='roundup', subject_person_id=None, caption='c', created_by='t')
    try:
        keys = _needs_render_keys(client)
        # Negative control: an artless roundup IS listed, so the filter is
        # about brand posts and not a listing that returns nothing.
        assert roundup in keys
        assert brand not in keys
    finally:
        _cancel(brand)
        _cancel(roundup)


def test_a_storage_failure_at_approval_keeps_the_calendar_slot(client, monkeypatch, make_person):
    """Approve, storage fails, the row reverts. It used to revert with its
    slot cleared, so pressing Approve again put the post out at the next
    default slot, days early."""
    import service.spotlight.storage as st
    A = _admin_headers(make_person)
    when = _soon(days=4)
    rk = _create(client, when=when).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        qid = _rows(rk)[0]['id']

        def boom(key):
            raise RuntimeError('storage down')
        monkeypatch.setattr(st, 'make_public', boom)
        r = _approve(client, A, qid)
        assert r.status_code == 503
        row = _rows(rk)[0]
        assert row['status'] == 'review'
        assert row['scheduled_for'] == when, 'the revert threw the calendar slot away'

        monkeypatch.setattr(st, 'make_public', lambda key: None)
        assert _approve(client, A, qid).status_code == 200
        assert _rows(rk)[0]['scheduled_for'] == when
    finally:
        _cancel(rk)


def test_a_future_slot_that_became_a_rest_day_rolls_forward_from_itself(client, monkeypatch, make_person):
    """The owner's projected dates can move. A post queued for a day that is
    later entered as a rest day rolls to the next valid slot AFTER its own
    time, never to one earlier in the week."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    when = _soon(days=5).replace(hour=12, minute=30, second=0)
    rk = _create(client, when=when).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        monkeypatch.setattr(rd, 'REST_DAYS', (when.astimezone(rd.BARBADOS).date(),))
        assert _approve(client, A, _rows(rk)[0]['id']).status_code == 200
        slot = _rows(rk)[0]['scheduled_for']
        assert slot > when, f'rolled to {slot}, earlier than the intended {when}'
        assert rd.slot_problem(slot, datetime.now(timezone.utc)) is None
    finally:
        _cancel(rk)


def test_dispatch_refuses_a_brand_post_past_the_known_calendar(client, monkeypatch, make_person):
    """Creation and approval refuse a brand post past the last date the
    owner's calendar has been read for; dispatch does too, so one moved
    there by hand cannot slip out. A member card is not held to it: with no
    rest days entered there is nothing to refuse on, which is where member
    cards stood before any of this."""
    brand = _create(client).get_json()['request_key']
    p = _make_eligible(make_person)
    with api_tx() as tx:
        member = _member_card(tx, p['id'])
    try:
        _render(client, monkeypatch, brand)
        monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() - timedelta(days=2))
        with _publication_on(), api_tx() as tx:
            rows = {r['kind']: r for r in _claimed(tx, brand) + _claimed(tx, member)}
            assert dispatch_check(tx, rows['brand']['id'], rows['brand']['lease_token']) == (False, 'calendar_unknown')
            assert dispatch_check(tx, rows['welcome']['id'], rows['welcome']['lease_token']) == (True, '')
    finally:
        _cancel(brand)
        _cancel(member)


def test_a_brand_post_cannot_be_rescheduled_onto_a_rest_day_or_into_the_past(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        qid = _rows(rk)[0]['id']
        assert _approve(client, A, qid).status_code == 200
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        r = client.post(f'/admin/growth/queue/{qid}/reschedule',
                        json=dict(scheduled_for=past.isoformat()), headers=A)
        assert r.status_code == 409 and r.get_json() == dict(error='slot_unavailable', reason='past')
        sabbath = (datetime.now(rd.BARBADOS) + timedelta(days=6)).date()
        monkeypatch.setattr(rd, 'REST_DAYS', (sabbath,))
        bad = datetime.combine(sabbath, datetime.min.time(), rd.BARBADOS).replace(hour=10)
        r = client.post(f'/admin/growth/queue/{qid}/reschedule',
                        json=dict(scheduled_for=bad.isoformat()), headers=A)
        assert r.status_code == 409 and r.get_json()['reason'] == 'rest_day'
    finally:
        _cancel(rk)


def test_retrying_a_failed_brand_post_rolls_forward_instead_of_publishing_at_once(client, monkeypatch, make_person):
    A = _admin_headers(make_person)
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        qid = _rows(rk)[0]['id']
        with api_tx() as tx:
            tx.execute("""UPDATE publishing_queue SET status = 'failed', scheduled_for = NOW() - interval '1 day'
                           WHERE id = %(id)s""", dict(id=qid))
        before = datetime.now(timezone.utc)
        r = client.post(f'/admin/growth/queue/{qid}/retry', json={}, headers=A)
        assert r.status_code == 200, r.get_json()
        row = [x for x in _rows(rk) if x['id'] == qid][0]
        assert row['status'] == 'scheduled'
        assert row['scheduled_for'] > before
    finally:
        _cancel(rk)


def test_a_platforms_list_holding_an_object_is_a_400_not_a_500(client):
    r = client.post('/admin/growth/brand', headers=H, json=dict(
        slug=_slug(), caption='c', scheduled_for=_soon().isoformat(), platforms=[{'x': 1}]))
    assert r.status_code == 400 and r.get_json() == dict(error='bad_platforms')


def test_a_member_with_an_open_card_is_not_offered_a_second(make_person):
    """One member was sent two card-ready emails for two separate cards in
    September 2026, because only published cards counted as recent. An open
    card now blocks another; once it is cancelled a new one is allowed."""
    p = _make_eligible(make_person, name='OneOffer')
    with api_tx() as tx:
        first = create_candidate(tx, kind='member_of_week', subject_person_id=p['id'], caption='c', created_by='t')
    with pytest.raises(ValueError, match='already_offered'):
        with api_tx() as tx:
            create_candidate(tx, kind='member_of_week', subject_person_id=p['id'], caption='c', created_by='t')
    _cancel(first)
    with api_tx() as tx:
        second = create_candidate(tx, kind='member_of_week', subject_person_id=p['id'], caption='c', created_by='t')
    _cancel(second)
