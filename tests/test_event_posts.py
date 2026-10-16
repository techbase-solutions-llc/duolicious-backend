"""Event posts (growth spec, Scheduler; TEC-1845).

When a gathering publishes, two feed posts are queued: 10 days and 2 days
before, at 12:00 UTC. A post whose day has passed is skipped; one whose day
is a rest day moves up to 2 days earlier, never later and never after the
gathering starts. A gathering months away is queued anyway, and approval
waits until the owner's calendar has been read that far. Approval and retry
hold to the same rule: a slot that has gone or turned out to be a rest day
moves earlier, never later, and a post with no slot left before the
gathering is refused as too late. The posts link to the gathering's own
page. Helpers are copied from tests/test_growth_kinds.py on purpose: test
files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from PIL import Image

import service.spotlight.restdays as rd
from database import api_tx
from service.config import WEB_BASE_URL
from service.spotlight.growthposts import cancel_event_posts, queue_event_posts

pytestmark = pytest.mark.usefixtures('growth_schema')

CAPTION = 'Gathering for Sukkot in Atlanta. Singles welcome.'
H = {'X-Growth-Cron': 'test-cron-secret'}


@pytest.fixture
def slug():
    s = f'ev{uuid4().hex[:8]}'
    yield s
    with api_tx() as tx:
        keys = [r['request_key'] for r in tx.execute(
            'SELECT DISTINCT request_key FROM publishing_queue WHERE request_key LIKE %(p)s',
            dict(p=f'event:{s}:%')).fetchall()]
        tx.execute('DELETE FROM publishing_queue WHERE request_key = ANY(%(k)s)', dict(k=keys))
        tx.execute('DELETE FROM spotlight_revision WHERE request_key = ANY(%(k)s)', dict(k=keys))
        tx.execute('DELETE FROM campaign_link WHERE kind = ANY(%(k)s)',
                   dict(k=[f'post:{k}' for k in keys]))


def _starts(days: int) -> datetime:
    day = (datetime.now(timezone.utc) + timedelta(days=days)).date()
    return datetime.combine(day, time(19, 0), timezone.utc)


def _queue(slug, starts_at, **kw):
    with api_tx() as tx:
        return queue_event_posts(tx, slug=slug, starts_at=starts_at, caption=CAPTION,
                                 payload=dict(title='Sukkot gathering', city='Atlanta'),
                                 created_by='test', **kw)


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id, kind, platform, status, scheduled_for, payload, subject_person_id
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def _jpeg() -> str:
    buf = io.BytesIO()
    Image.new('RGB', (1080, 1350), 'white').save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _rendered(client, monkeypatch, rk) -> None:
    """Artwork on both platform rows, so the post waits in review."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    for platform in ('facebook', 'instagram'):
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform=platform, image_base64=_jpeg(), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _admin_headers(make_person) -> dict:
    p = make_person(name='EventAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _approve(client, headers, rk):
    """Approves the facebook row, the first of _rows."""
    return client.post(f"/admin/growth/queue/{_rows(rk)[0]['id']}/approve", json={}, headers=headers)


def test_a_gathering_gets_two_posts_ten_and_two_days_before(slug, monkeypatch):
    # No rest days and a calendar read far ahead, so only the offsets decide
    # the slot whatever day this runs.
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    starts = _starts(20)
    keys = _queue(slug, starts)
    stamp = f'{starts:%Y%m%d}'
    assert keys == [f'event:{slug}:{stamp}:d10', f'event:{slug}:{stamp}:d2']
    for rk, offset in zip(keys, (10, 2)):
        rows = _rows(rk)
        assert {(r['kind'], r['status'], r['subject_person_id']) for r in rows} == {
            ('event', 'awaiting_render', None)}
        want = datetime.combine(starts.date() - timedelta(days=offset), time(12, 0), timezone.utc)
        assert {r['scheduled_for'] for r in rows} == {want}
        assert rows[0]['payload'] == dict(title='Sukkot gathering', city='Atlanta',
                                          offset_days=offset, starts_at=starts.isoformat())
    with api_tx('read committed') as tx:
        target = tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                            dict(k=f'post:{keys[0]}')).fetchone()['target_url']
    assert target == f"{WEB_BASE_URL.rstrip('/')}/e/{slug}?utm_campaign=event&utm_content={slug}"


def test_queuing_twice_changes_nothing(slug):
    starts = _starts(20)
    first = _queue(slug, starts)
    assert _queue(slug, starts) == []
    assert all(len(_rows(rk)) == 2 for rk in first)


def test_an_offset_already_past_is_skipped(slug):
    keys = _queue(slug, _starts(5))
    assert [k.rsplit(':', 1)[1] for k in keys] == ['d2']


def test_a_gathering_tomorrow_gets_no_post(slug):
    assert _queue(slug, datetime.now(timezone.utc) + timedelta(days=1)) == []


def test_a_rest_day_moves_the_post_earlier(slug, monkeypatch):
    starts = _starts(20)
    rest = starts.date() - timedelta(days=10)
    monkeypatch.setattr(rd, 'REST_DAYS', (rest,))
    keys = _queue(slug, starts)
    moved = {r['scheduled_for'] for r in _rows(keys[0])}
    assert moved == {datetime.combine(rest - timedelta(days=1), time(12, 0), timezone.utc)}


def test_a_gathering_past_the_known_calendar_is_still_queued(slug, monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=3))
    keys = _queue(slug, _starts(30))
    assert len(keys) == 2
    for rk in keys:
        slot = _rows(rk)[0]['scheduled_for']
        assert rd.slot_problem(slot) == 'unknown'


def test_a_moved_gathering_gets_new_posts_and_the_old_ones_are_cancelled(slug):
    old = _queue(slug, _starts(20))
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'published' WHERE request_key = %(rk)s",
                   dict(rk=old[1]))
        assert cancel_event_posts(tx, slug) == 2
    assert {r['status'] for r in _rows(old[0])} == {'cancelled'}
    assert {r['status'] for r in _rows(old[1])} == {'published'}, 'a post already out stays'
    new = _queue(slug, _starts(25))
    assert len(new) == 2 and not set(new) & set(old)


def test_a_late_approval_of_the_d2_post_is_refused_never_moved_after_the_gathering(
        slug, client, monkeypatch, make_person):
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    headers = _admin_headers(make_person)
    rk = _queue(slug, _starts(20))[1]
    _rendered(client, monkeypatch, rk)
    # The approval comes late: the gathering starts in 3 hours and every
    # slot the d2 post may take, on its day or up to 2 days before, is gone.
    soon = datetime.now(timezone.utc) + timedelta(hours=3)
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue
                         SET scheduled_for = %(w)s,
                             payload = payload || jsonb_build_object('starts_at', %(s)s::text)
                       WHERE request_key = %(rk)s""",
                   dict(w=soon - timedelta(days=2), s=soon.isoformat(), rk=rk))
    r = _approve(client, headers, rk)
    assert r.status_code == 409
    assert r.get_json() == dict(error='slot_unavailable', reason='too_late')
    assert {x['status'] for x in _rows(rk)} == {'review'}


def test_a_slot_that_turns_out_to_be_a_rest_day_moves_earlier_on_approval(
        slug, client, monkeypatch, make_person):
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=3))
    headers = _admin_headers(make_person)
    starts = _starts(30)
    rk = _queue(slug, starts)[0]
    stored = _rows(rk)[0]['scheduled_for']
    assert rd.slot_problem(stored) == 'unknown'
    _rendered(client, monkeypatch, rk)
    # The owner's calendar is read further, and the post's day is a rest day.
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    monkeypatch.setattr(rd, 'REST_DAYS', (stored.date(),))
    r = _approve(client, headers, rk)
    assert r.status_code == 200, r.get_json()
    slot = _rows(rk)[0]['scheduled_for']
    assert slot == datetime.combine(stored.date() - timedelta(days=1), time(12, 0), timezone.utc)
    assert slot < starts


@pytest.mark.parametrize('kw,error', [
    (dict(slug='Not A Slug'), 'bad_slug'),
    (dict(caption=''), 'bad_caption'),
    (dict(caption='x' * 2001), 'bad_caption'),
    (dict(payload=['title']), 'bad_payload'),
    (dict(starts_at=datetime(2027, 1, 1, 19, 0)), 'naive datetime'),
])
def test_bad_input_is_refused(slug, kw, error):
    args = dict(slug=slug, starts_at=_starts(20), caption=CAPTION, payload={}, created_by='test')
    args.update(kw)
    with pytest.raises(ValueError, match=error):
        with api_tx() as tx:
            queue_event_posts(tx, **args)
