"""Carousel posts: one queue row, 2 to 10 slides (TEC-1845).

ahavah-admin docs/plans/2026-11-02-carousel-posts.md. A calendar entry with
`images` becomes a brand post whose queue row carries `slide_count`; each
slide arrives through the image route with its position, and the row moves
to review only once every slide is there. The row's own image columns hold
slide 1, so the thumbnail, the render completion, `dispatch_check` and the
revision keep working as they do for a single image.

Session and request helpers are copied from tests/test_brand_posts.py on
purpose: test files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from PIL import Image

from database import api_tx
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('carousel_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}
MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0090_carousel_slides.sql'


def _slug() -> str:
    return f'test-{secrets.token_hex(4)}'


def _brand_row(platforms=('facebook',)) -> tuple[str, str]:
    with api_tx() as tx:
        rk = create_candidate(tx, kind='brand', subject_person_id=None, caption='c', created_by='t',
                              platforms=list(platforms), request_key=f'brand:{_slug()}')
        qid = tx.execute("SELECT id FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform LIMIT 1",
                         dict(rk=rk)).fetchone()['id']
    return rk, qid


def _cancel(rk: str) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'cancelled', updated_at = NOW()
                       WHERE request_key = %(rk)s
                         AND status IN ('scheduled', 'processing', 'review', 'awaiting_render', 'awaiting_member')""",
                   dict(rk=rk))


# ---------------------------------------------------------------------------
# A1. The migration
# ---------------------------------------------------------------------------

def test_the_migration_applies_twice_cleanly():
    sql = MIGRATION.read_text(encoding='utf-8')
    for _ in range(2):
        with api_tx() as tx:
            tx.execute(sql)
    with api_tx('read committed') as tx:
        assert tx.execute("""SELECT 1 FROM information_schema.columns
                              WHERE table_name = 'publishing_queue' AND column_name = 'slide_count'""").fetchone()
        assert tx.execute("SELECT to_regclass('publishing_queue_slide') AS t").fetchone()['t'] is not None


@pytest.mark.parametrize('count', [1, 11, 0, -1])
def test_a_slide_count_outside_2_to_10_is_refused(count):
    rk, qid = _brand_row()
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("UPDATE publishing_queue SET slide_count = %(n)s WHERE id = %(id)s",
                           dict(n=count, id=qid))
    finally:
        _cancel(rk)


@pytest.mark.parametrize('count', [None, 2, 10])
def test_a_slide_count_of_null_or_2_to_10_is_kept(count):
    rk, qid = _brand_row()
    try:
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET slide_count = %(n)s WHERE id = %(id)s", dict(n=count, id=qid))
            assert tx.execute("SELECT slide_count FROM publishing_queue WHERE id = %(id)s",
                              dict(id=qid)).fetchone()['slide_count'] == count
    finally:
        _cancel(rk)


@pytest.mark.parametrize('position', [0, 11])
def test_a_slide_position_outside_1_to_10_is_refused(position):
    rk, qid = _brand_row()
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO publishing_queue_slide (queue_id, position) VALUES (%(q)s, %(n)s)",
                           dict(q=qid, n=position))
    finally:
        _cancel(rk)


def test_deleting_a_queue_row_removes_its_slides():
    rk, qid = _brand_row()
    with api_tx() as tx:
        for n in (1, 2):
            tx.execute("""INSERT INTO publishing_queue_slide (queue_id, position, image_key, image_url, image_sha256)
                          VALUES (%(q)s, %(n)s, %(k)s, %(u)s, 'h')""",
                       dict(q=qid, n=n, k=f'spotlight/{rk}/s{n}.jpg', u=f'https://cdn/s{n}.jpg'))
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(rk)s", dict(rk=rk))
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM publishing_queue_slide WHERE queue_id = %(q)s",
                          dict(q=qid)).fetchone()['n'] == 0


# ---------------------------------------------------------------------------
# A3. The image route takes `slide`
# ---------------------------------------------------------------------------

def _jpeg(shade: int = 0, w: int = 1080, h: int = 1350) -> str:
    """A distinct picture per shade, so each slide hashes differently."""
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (shade, 255 - shade, 128)).save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _soon(days: int = 2) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0)


def _carousel(client, slides=7, platforms=('facebook',)) -> str:
    r = client.post('/admin/growth/brand', headers=H, json=dict(
        slug=_slug(), caption='How a family can help, on Ahavah.', scheduled_for=_soon().isoformat(),
        platforms=list(platforms), slides=slides))
    assert r.status_code == 200, r.get_json()
    return r.get_json()['request_key']


@pytest.fixture
def stored(monkeypatch):
    """Every object the route writes, by key, instead of the object store."""
    import service.spotlight.storage as st
    objects: dict = {}
    monkeypatch.setattr(st, 'put_card_image',
                        lambda key, data, content_type, public=False: objects.__setitem__(key, data))
    return objects


def _upload(client, rk, slide=None, shade=None, platform='facebook', w=1080, h=1350):
    if shade is None:
        shade = (slide if isinstance(slide, int) else 0) * 20
    body = dict(platform=platform, image_base64=_jpeg(shade, w, h), content_type='image/jpeg')
    if slide is not None:
        body['slide'] = slide
    return client.post(f'/admin/growth/queue/{rk}/image', json=body, headers=H)


def _row(rk, platform='facebook') -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(
            """SELECT q.id, q.status, q.image_key, q.image_url, q.image_sha256, q.slide_count,
                      r.asset_hash, r.image_key AS revision_key
                 FROM publishing_queue q
                 LEFT JOIN spotlight_revision r ON r.id = q.current_revision_id
                WHERE q.request_key = %(rk)s AND q.platform = %(pl)s""",
            dict(rk=rk, pl=platform)).fetchone())


def _slides(qid) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT position, image_key, image_url, image_sha256, updated_at
                 FROM publishing_queue_slide WHERE queue_id = %(q)s ORDER BY position""",
            dict(q=qid)).fetchall()]


def _pending_delete(key) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute("""SELECT 1 FROM cleanup_job WHERE kind = 'asset_delete' AND target = %(k)s
                               AND state = 'pending'""", dict(k=key)).fetchone() is not None


def test_six_of_seven_slides_leave_the_row_waiting_and_the_seventh_moves_it_to_review(client, stored):
    rk = _carousel(client)
    try:
        for n in range(1, 7):
            r = _upload(client, rk, slide=n)
            assert r.status_code == 200, r.get_json()
            row = _row(rk)
            assert row['status'] == 'awaiting_render'
            assert row['image_key'] is None and row['asset_hash'] is None
        slides = _slides(row['id'])
        assert [s['position'] for s in slides] == [1, 2, 3, 4, 5, 6]
        assert all(s['image_key'].endswith(f"-facebook-{s['position']}.jpg") for s in slides)
        assert set(stored) == {s['image_key'] for s in slides}

        r = _upload(client, rk, slide=7)
        assert r.status_code == 200, r.get_json()
        row = _row(rk)
        slides = _slides(row['id'])
        assert row['status'] == 'review'
        assert (row['image_key'], row['image_url'], row['image_sha256']) == (
            slides[0]['image_key'], slides[0]['image_url'], slides[0]['image_sha256'])
        assert row['asset_hash'] == slides[0]['image_sha256']
        assert row['revision_key'] == slides[0]['image_key']
        assert len({s['image_key'] for s in slides}) == 7
    finally:
        _cancel(rk)


def test_slides_may_arrive_in_any_order(client, stored):
    rk = _carousel(client, slides=3)
    try:
        for n in (3, 1, 2):
            assert _upload(client, rk, slide=n).status_code == 200
        row = _row(rk)
        assert row['status'] == 'review'
        assert row['image_key'] == _slides(row['id'])[0]['image_key']
    finally:
        _cancel(rk)


def test_the_same_bytes_again_change_nothing(client, stored):
    rk = _carousel(client)
    try:
        assert _upload(client, rk, slide=2).status_code == 200
        qid = _row(rk)['id']
        before = _slides(qid)
        again = _upload(client, rk, slide=2)
        assert again.status_code == 200, again.get_json()
        assert _slides(qid) == before
        assert not _pending_delete(before[0]['image_key'])
    finally:
        _cancel(rk)


def test_different_bytes_replace_the_slide_and_queue_the_old_object(client, stored):
    rk = _carousel(client)
    try:
        assert _upload(client, rk, slide=2, shade=10).status_code == 200
        qid = _row(rk)['id']
        old = _slides(qid)[0]['image_key']
        assert _upload(client, rk, slide=2, shade=200).status_code == 200
        new = _slides(qid)
        assert len(new) == 1 and new[0]['position'] == 2
        assert new[0]['image_key'] != old
        assert _pending_delete(old)
        assert not _pending_delete(new[0]['image_key'])
    finally:
        _cancel(rk)


def test_once_every_slide_is_there_any_slide_upload_is_already_rendered(client, stored):
    rk = _carousel(client, slides=2)
    try:
        for n in (1, 2):
            assert _upload(client, rk, slide=n).status_code == 200
        for n, shade in ((1, 20), (2, 40), (2, 250)):
            r = _upload(client, rk, slide=n, shade=shade)
            assert r.status_code == 409 and r.get_json() == dict(error='already_rendered')
    finally:
        _cancel(rk)


@pytest.mark.parametrize('slide', [None, 0, 8, -1, '1', True, 1.5])
def test_a_carousel_row_refuses_a_missing_or_wrong_slide(client, stored, slide):
    rk = _carousel(client)
    try:
        r = _upload(client, rk, slide=slide, shade=5)
        assert r.status_code == 400 and r.get_json() == dict(error='bad_slide')
        assert _slides(_row(rk)['id']) == [] and stored == {}
    finally:
        _cancel(rk)


def test_a_single_image_row_refuses_a_slide(client, stored):
    r = client.post('/admin/growth/brand', headers=H, json=dict(
        slug=_slug(), caption='c', scheduled_for=_soon().isoformat(), platforms=['facebook']))
    rk = r.get_json()['request_key']
    try:
        r = _upload(client, rk, slide=1)
        assert r.status_code == 400 and r.get_json() == dict(error='bad_slide')
        assert stored == {}
        ok = _upload(client, rk)
        assert ok.status_code == 200, ok.get_json()
        assert _row(rk)['status'] == 'review'
    finally:
        _cancel(rk)


def test_a_square_image_on_a_carousel_row_is_refused(client, stored):
    rk = _carousel(client)
    try:
        r = _upload(client, rk, slide=1, w=1080, h=1080)
        assert r.status_code == 400 and r.get_json() == dict(error='invalid_image', reason='bad_dimensions')
        assert stored == {}
    finally:
        _cancel(rk)


def test_the_existing_checks_run_before_the_slide_check(client, stored):
    rk = _carousel(client)
    _cancel(rk)
    r = _upload(client, rk, slide=99)
    assert r.status_code == 409 and r.get_json() == dict(error='bad_status')


# ---------------------------------------------------------------------------
# A4. Approve makes every slide public
# ---------------------------------------------------------------------------

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
    p = make_person(name='CarouselAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return {'Authorization': f'Bearer {_session_for(p)}'}


def _rendered_carousel(client, slides=7) -> tuple[str, dict, list[dict]]:
    rk = _carousel(client, slides=slides)
    for n in range(1, slides + 1):
        r = _upload(client, rk, slide=n)
        assert r.status_code == 200, r.get_json()
    row = _row(rk)
    assert row['status'] == 'review'
    return rk, row, _slides(row['id'])


def test_approve_makes_every_slide_public_in_order(client, stored, monkeypatch, make_person):
    import service.spotlight.storage as st
    A = _admin_headers(make_person)
    rk, row, slides = _rendered_carousel(client)
    flipped: list = []
    monkeypatch.setattr(st, 'make_public', flipped.append)
    try:
        r = client.post(f"/admin/growth/queue/{row['id']}/approve", json={}, headers=A)
        assert r.status_code == 200, r.get_json()
        assert flipped == [s['image_key'] for s in slides]
        assert flipped[0] == row['image_key']
        assert _row(rk)['status'] == 'scheduled'
    finally:
        _cancel(rk)


def test_a_storage_failure_on_slide_4_reverts_the_row(client, stored, monkeypatch, make_person):
    import service.spotlight.storage as st
    A = _admin_headers(make_person)
    rk, row, slides = _rendered_carousel(client)
    with api_tx('read committed') as tx:
        slot = tx.execute("SELECT scheduled_for FROM publishing_queue WHERE id = %(id)s",
                          dict(id=row['id'])).fetchone()['scheduled_for']
    flipped: list = []

    def flip(key):
        if key == slides[3]['image_key']:
            raise RuntimeError('storage down')
        flipped.append(key)

    monkeypatch.setattr(st, 'make_public', flip)
    try:
        r = client.post(f"/admin/growth/queue/{row['id']}/approve", json={}, headers=A)
        assert r.status_code == 503 and r.get_json() == dict(error='storage_unavailable', in_flight=False)
        assert flipped == [s['image_key'] for s in slides[:3]]
        with api_tx('read committed') as tx:
            after = tx.execute("SELECT status, scheduled_for FROM publishing_queue WHERE id = %(id)s",
                               dict(id=row['id'])).fetchone()
        assert after['status'] == 'review' and after['scheduled_for'] == slot
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# A5. Claim and dispatch
# ---------------------------------------------------------------------------

@contextmanager
def _publication_on():
    from service.spotlight.queue import set_setting
    with api_tx() as tx:
        set_setting(tx, 'publication_enabled', 'true')
        set_setting(tx, 'external_access_enabled', 'true')
    try:
        yield
    finally:
        with api_tx() as tx:
            set_setting(tx, 'publication_enabled', 'false')
            set_setting(tx, 'external_access_enabled', 'true')


def _due_first(rk: str) -> None:
    """Scheduled and older than anything else in the shared database, so a
    claim of 1 takes this row and nothing another test left behind."""
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'scheduled',
                             scheduled_for = NOW() - interval '3650 days'
                       WHERE request_key = %(rk)s""", dict(rk=rk))


def test_claim_returns_every_slide_url_in_order(client, stored):
    rk, row, slides = _rendered_carousel(client)
    _due_first(rk)
    try:
        with _publication_on():
            r = client.post('/admin/growth/queue/claim', json=dict(max=1), headers=H)
        assert r.status_code == 200, r.get_json()
        claimed = [c for c in r.get_json()['claimed'] if c['request_key'] == rk]
        assert len(claimed) == 1
        assert claimed[0]['image_urls'] == [s['image_url'] for s in slides]
        assert claimed[0]['image_url'] == slides[0]['image_url']
        assert claimed[0]['slide_count'] == 7
    finally:
        _cancel(rk)


def test_a_claimed_single_image_row_has_no_image_urls(client, stored):
    r = client.post('/admin/growth/brand', headers=H, json=dict(
        slug=_slug(), caption='c', scheduled_for=_soon().isoformat(), platforms=['facebook']))
    rk = r.get_json()['request_key']
    try:
        assert _upload(client, rk).status_code == 200
        _due_first(rk)
        with _publication_on():
            r = client.post('/admin/growth/queue/claim', json=dict(max=1), headers=H)
        claimed = [c for c in r.get_json()['claimed'] if c['request_key'] == rk]
        assert len(claimed) == 1
        assert 'image_urls' not in claimed[0]
        assert claimed[0]['slide_count'] is None
    finally:
        _cancel(rk)


def _claim_in_tx(tx, rk):
    tx.execute("""UPDATE publishing_queue SET status = 'scheduled',
                         scheduled_for = NOW() - interval '3650 days'
                   WHERE request_key = %(rk)s""", dict(rk=rk))
    return [r for r in tx.execute("SELECT * FROM claim_spotlight_posts(1)").fetchall()
            if r['request_key'] == rk]


def test_a_whole_carousel_passes_dispatch(client, stored):
    from service.spotlight.dispatch import dispatch_check
    rk, row, slides = _rendered_carousel(client, slides=3)
    try:
        with _publication_on(), api_tx() as tx:
            (claimed,) = _claim_in_tx(tx, rk)
            assert dispatch_check(tx, claimed['id'], claimed['lease_token']) == (True, '')
    finally:
        _cancel(rk)


@pytest.mark.parametrize('damage', ['delete', 'no_url', 'no_key'])
def test_a_carousel_with_a_slide_missing_fails_dispatch(client, stored, damage):
    from service.spotlight.dispatch import dispatch_check
    rk, row, slides = _rendered_carousel(client, slides=7)
    try:
        with _publication_on(), api_tx() as tx:
            (claimed,) = _claim_in_tx(tx, rk)
            sql = {
                'delete': "DELETE FROM publishing_queue_slide WHERE queue_id = %(q)s AND position = 4",
                'no_url': "UPDATE publishing_queue_slide SET image_url = NULL WHERE queue_id = %(q)s AND position = 4",
                'no_key': "UPDATE publishing_queue_slide SET image_key = NULL WHERE queue_id = %(q)s AND position = 4",
            }[damage]
            tx.execute(sql, dict(q=claimed['id']))
            assert dispatch_check(tx, claimed['id'], claimed['lease_token']) == (False, 'slides_incomplete')
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# A6. The lifecycle of slide objects
# ---------------------------------------------------------------------------

def _published_long_ago(rk: str) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'published', delivery_state = 'published',
                             updated_at = NOW() - interval '120 days'
                       WHERE request_key = %(rk)s""", dict(rk=rk))


def test_a_slide_key_counts_as_referenced(client, stored):
    from service.spotlight.cleanup import is_referenced
    rk = _carousel(client, slides=3)
    try:
        assert _upload(client, rk, slide=3).status_code == 200
        (s3,) = _slides(_row(rk)['id'])
        with api_tx('read committed') as tx:
            assert is_referenced(tx, s3['image_key'])
            assert not is_referenced(tx, s3['image_key'] + '.gone')
    finally:
        _cancel(rk)


def test_the_cleanup_batch_leaves_a_slide_that_came_back_alone(client, stored):
    """A key queued while nothing named it, then named by a slide before
    the batch ran: the slide is a new owner, so the object stays."""
    from service.spotlight import cleanup
    rk = _carousel(client, slides=3)
    try:
        assert _upload(client, rk, slide=2).status_code == 200
        (s2,) = _slides(_row(rk)['id'])
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO cleanup_job (kind, target, evidence)
                   VALUES ('asset_delete', %(k)s, '{"owners": []}'::jsonb)""", dict(k=s2['image_key']))
        deleted: list = []
        cleanup.run_cleanup_batch(api_tx, delete=lambda keys: deleted.extend(keys) or list(keys),
                                  target_prefix=f'spotlight/{rk}/')
        assert deleted == []
        assert _slides(_row(rk)['id'])[0]['image_key'] == s2['image_key']
    finally:
        _cancel(rk)


def test_the_cleanup_batch_clears_a_confirmed_slide_key(client, stored):
    from service.spotlight import cleanup
    from service.spotlight.cleanup import enqueue_asset_delete
    rk, row, slides = _rendered_carousel(client, slides=3)
    try:
        _published_long_ago(rk)
        with api_tx() as tx:
            for s in slides:
                enqueue_asset_delete(tx, s['image_key'])
        out = cleanup.run_cleanup_batch(api_tx, delete=lambda keys: list(keys),
                                        target_prefix=f'spotlight/{rk}/')
        assert out['done'] == 3
        assert all(s['image_key'] is None and s['image_url'] is None and s['image_sha256'] is None
                   for s in _slides(row['id']))
        assert _row(rk)['image_key'] is None
    finally:
        _cancel(rk)


def test_the_retention_sweep_queues_every_slide_of_an_old_published_carousel(client, stored):
    from service.cron.spotlightretention import retention_sweep
    rk, row, slides = _rendered_carousel(client, slides=4)
    try:
        _published_long_ago(rk)
        with api_tx() as tx:
            # Slide 3's earlier job ran out of attempts: a human has to look,
            # and the sweep must not file a fresh one every day.
            tx.execute("""INSERT INTO cleanup_job (kind, target, state, attempts)
                          VALUES ('asset_delete', %(k)s, 'abandoned', 10)""",
                       dict(k=slides[2]['image_key']))
            retention_sweep(tx)
        assert [_pending_delete(s['image_key']) for s in slides] == [True, True, False, True]
    finally:
        _cancel(rk)
        # The suite shares one database: an abandoned job left behind would
        # crowd the abandoned listing other tests read.
        with api_tx() as tx:
            tx.execute("DELETE FROM cleanup_job WHERE target LIKE %(p)s", dict(p=f'spotlight/{rk}/%'))


def test_the_retention_sweep_leaves_a_recent_carousel_alone(client, stored):
    from service.cron.spotlightretention import retention_sweep
    rk, row, slides = _rendered_carousel(client, slides=2)
    try:
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET status = 'published' WHERE request_key = %(rk)s",
                       dict(rk=rk))
            retention_sweep(tx)
        assert [_pending_delete(s['image_key']) for s in slides] == [False, False]
    finally:
        _cancel(rk)


def test_a_removal_marked_done_queues_every_slide(client, stored):
    rk, row, slides = _rendered_carousel(client, slides=3)
    try:
        with api_tx() as tx:
            tx.execute("""UPDATE publishing_queue SET status = 'published', delivery_state = 'published',
                                 external_post_id = 'fb-1' WHERE id = %(id)s""", dict(id=row['id']))
            task_id = tx.execute(
                """INSERT INTO spotlight_removal_task (queue_id, platform, external_post_id, reason)
                   VALUES (%(q)s, 'facebook', 'fb-1', 'delete_via_api') RETURNING id""",
                dict(q=row['id'])).fetchone()['id']
        r = client.post(f'/admin/growth/removals/{task_id}/done', json={}, headers=H)
        assert r.status_code == 200, r.get_json()
        assert [_pending_delete(s['image_key']) for s in slides] == [True, True, True]
    finally:
        _cancel(rk)


def test_the_caption_route_refuses_a_carousel(client, stored, make_person):
    A = _admin_headers(make_person)
    rk, row, slides = _rendered_carousel(client, slides=2)
    try:
        r = client.post(f"/admin/growth/queue/{row['id']}/caption", json=dict(caption='New words'), headers=A)
        assert r.status_code == 409 and r.get_json() == dict(error='carousel_caption')
        after = _row(rk)
        assert after['image_key'] == row['image_key'] and after['status'] == 'review'
        assert _slides(row['id']) == slides
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# A7. The Growth tab listing
# ---------------------------------------------------------------------------

@pytest.fixture
def presigned(monkeypatch):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'presign', lambda key, seconds=900: f'https://signed.test/{key}')


def _listed(client, rk) -> list[dict]:
    r = client.get('/admin/growth/queue', headers=H)
    assert r.status_code == 200
    return [x for x in r.get_json() if x['request_key'] == rk]


def test_the_listing_gives_every_slide_preview_in_order(client, stored, presigned):
    rk, row, slides = _rendered_carousel(client)
    try:
        (listed,) = _listed(client, rk)
        assert listed['slide_count'] == 7
        assert listed['slides'] == [dict(position=s['position'], preview_url=f"https://signed.test/{s['image_key']}")
                                    for s in slides]
        assert listed['preview_url'] == f"https://signed.test/{slides[0]['image_key']}"
    finally:
        _cancel(rk)


def test_a_carousel_still_waiting_lists_the_slides_it_has(client, stored, presigned):
    rk = _carousel(client)
    try:
        for n in (2, 5):
            assert _upload(client, rk, slide=n).status_code == 200
        (listed,) = _listed(client, rk)
        assert listed['status'] == 'awaiting_render'
        assert listed['slide_count'] == 7
        assert [s['position'] for s in listed['slides']] == [2, 5]
    finally:
        _cancel(rk)


def test_a_single_image_row_carries_no_slide_keys(client, stored, presigned):
    r = client.post('/admin/growth/brand', headers=H, json=dict(
        slug=_slug(), caption='c', scheduled_for=_soon().isoformat(), platforms=['facebook']))
    rk = r.get_json()['request_key']
    try:
        assert _upload(client, rk).status_code == 200
        (listed,) = _listed(client, rk)
        assert 'slides' not in listed and 'slide_count' not in listed
    finally:
        _cancel(rk)


# ---------------------------------------------------------------------------
# Two slide uploads racing for one row (plan A3: 409 image_race, as now)
# ---------------------------------------------------------------------------
# Helpers copied from tests/test_spotlight_routes.py, on purpose: test files
# in this suite do not import from each other.

def _one_connection_per_tx(m):
    import database

    def _enter(self):
        self._own_conn = psycopg.Connection.connect(
            conninfo=database._api_conninfo, row_factory=psycopg.rows.dict_row)
        self.cur = self._own_conn.cursor()
        if self.isolation_level != database._default_transaction_isolation:
            self.cur.execute(f'SET TRANSACTION ISOLATION LEVEL {self.isolation_level}')
        return self.cur

    def _exit(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._own_conn.commit()
            else:
                self._own_conn.rollback()
        finally:
            self._own_conn.close()

    m.setattr(database.api_tx, '__enter__', _enter)
    m.setattr(database.api_tx, '__exit__', _exit)


def _wait_for_lock_waiter(pids, timeout: float = 10.0) -> bool:
    import time

    import database
    deadline = time.monotonic() + timeout
    with psycopg.connect(database._api_conninfo, autocommit=True) as conn:
        while time.monotonic() < deadline:
            n = conn.execute(
                """SELECT count(*) FROM pg_stat_activity
                    WHERE pid = ANY(%(p)s) AND wait_event_type = 'Lock'""",
                dict(p=list(pids))).fetchone()[0]
            if n:
                return True
            time.sleep(0.02)
    return False


def _burst(app, n, call):
    from concurrent.futures import ThreadPoolExecutor

    def worker(i):
        with app.test_client() as c:
            try:
                return call(c, i)
            except Exception as e:      # noqa: BLE001 -- recorded as the evidence
                return type(e).__name__
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def _status(result):
    return result[0] if isinstance(result, tuple) else result


@pytest.mark.parametrize('slides_raced', [(2, 3), (2, 2)], ids=['two-slides', 'one-slide-different-bytes'])
def test_two_racing_slide_uploads_one_lands_one_answers_image_race(client, app, monkeypatch, stored, slides_raced):
    """Two uploads for one carousel row at once: both pass the up-front
    checks, both upload, and both reach the slide table's lock. The first
    commits; the second is refused as `image_race` (409) rather than a 500
    or a silent overwrite, and its object, which nothing names, is queued
    for deletion. The row stays waiting for its other slides."""
    import threading

    import service.api.admin.spotlight_routes as sr
    rk = _carousel(client)
    try:
        barrier = threading.Barrier(2)
        pids: set = set()
        real_attach = sr.attach_slide

        def racing_attach(tx, *args):
            me = tx.connection.info.backend_pid
            pids.add(me)
            barrier.wait(timeout=30)
            outcome = real_attach(tx, *args)
            if outcome[0] == 'stored':
                # Hold this transaction open until the other upload's backend
                # is provably blocked on the row lock this one took.
                assert _wait_for_lock_waiter(pids - {me})
            return outcome

        shades = (40, 220)
        with monkeypatch.context() as m:
            _one_connection_per_tx(m)
            m.setattr(sr, 'attach_slide', racing_attach)

            def call(c, i):
                r = _upload(c, rk, slide=slides_raced[i], shade=shades[i])
                return (r.status_code, r.get_json(silent=True))

            results = _burst(app, 2, call)

        assert sorted(map(_status, results), key=str) == [200, 409], results
        winner = next(i for i, r in enumerate(results) if _status(r) == 200)
        loser = 1 - winner
        assert results[loser][1] == {'error': 'image_race'}
        row = _row(rk)
        assert row['status'] == 'awaiting_render' and row['image_key'] is None
        slides = _slides(row['id'])
        assert [s['position'] for s in slides] == [slides_raced[winner]]
        winner_key = slides[0]['image_key']
        assert results[winner][1]['image_url'].endswith(winner_key)
        # Both uploads reached storage; only the winner's object is named.
        loser_keys = [k for k in stored if k != winner_key]
        assert len(loser_keys) == 1, list(stored)
        assert _pending_delete(loser_keys[0])
        assert not _pending_delete(winner_key)
    finally:
        _cancel(rk)
