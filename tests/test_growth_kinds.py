"""The scheduler's three new kinds: event, prompt and tool (TEC-1845).

Each is about nobody and held to the owner's calendar exactly as a brand
post is: portrait artwork only, a late approval rolls forward (an event
post moves earlier instead, tests/test_event_posts.py), nothing is
dispatched past the known calendar or on a rest day. The render tick draws
member cards and roundups only, so it must never be handed one of these;
event and prompt rows wait for their template renderer on a listing of
their own. Helpers are copied from tests/test_brand_posts.py on purpose:
test files in this suite do not import from each other.
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

pytestmark = pytest.mark.usefixtures('growth_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}
NEW_KINDS = ('event', 'prompt', 'tool')


def _jpeg(w=1080, h=1350) -> str:
    buf = io.BytesIO()
    Image.new('RGB', (w, h), 'white').save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _candidate(kind: str) -> str:
    with api_tx() as tx:
        return create_candidate(tx, kind=kind, subject_person_id=None, caption='c', created_by='t')


def _rows(rk: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id, kind, platform, status, subject_person_id, scheduled_for
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def _cancel(rk: str) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'cancelled', updated_at = NOW()
                       WHERE request_key = %(rk)s
                         AND status IN ('scheduled', 'processing', 'review', 'awaiting_render', 'awaiting_member')""",
                   dict(rk=rk))


def _render(client, monkeypatch, rk, w=1080, h=1350):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    for platform in ('facebook', 'instagram'):
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform=platform, image_base64=_jpeg(w, h), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _admin_headers(make_person) -> dict:
    p = make_person(name='KindsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _listed(client, query: str) -> list[dict]:
    r = client.get(f'/admin/growth/queue?{query}', headers=H)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


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


def _claimed(tx, rk):
    tx.execute("""UPDATE publishing_queue SET status = 'scheduled',
                         scheduled_for = NOW() - interval '1 minute'
                   WHERE request_key = %(rk)s""", dict(rk=rk))
    return [r for r in tx.execute('SELECT * FROM claim_spotlight_posts(10)').fetchall()
            if r['request_key'] == rk]


@pytest.mark.parametrize('kind', NEW_KINDS)
def test_a_new_kind_is_about_nobody_and_waits_for_its_artwork(kind):
    rk = _candidate(kind)
    try:
        rows = _rows(rk)
        assert [r['platform'] for r in rows] == ['facebook', 'instagram']
        assert {(r['kind'], r['status'], r['subject_person_id']) for r in rows} == {
            (kind, 'awaiting_render', None)}
    finally:
        _cancel(rk)


@pytest.mark.parametrize('kind', NEW_KINDS)
def test_a_new_kind_with_a_subject_is_refused(kind, make_person):
    p = make_person(name='KindSubject')
    with pytest.raises(ValueError, match='roundup_has_no_subject'):
        with api_tx() as tx:
            create_candidate(tx, kind=kind, subject_person_id=p['id'], caption='c', created_by='t')


def test_the_tick_sees_none_of_them_and_the_template_listing_sees_event_and_prompt(client):
    keys = {kind: _candidate(kind) for kind in (*NEW_KINDS, 'roundup')}
    try:
        tick = {r['request_key'] for r in _listed(client, 'needs_render=1')}
        template = {r['request_key'] for r in _listed(client, 'template_render=1')}
        assert keys['roundup'] in tick, 'negative control: an artless roundup is listed'
        assert not {keys['event'], keys['prompt'], keys['tool']} & tick
        assert {keys['event'], keys['prompt']} <= template
        assert keys['tool'] not in template and keys['roundup'] not in template
    finally:
        for rk in keys.values():
            _cancel(rk)


@pytest.mark.parametrize('w,h,ok', [(1080, 1350, True), (1080, 1080, False)])
def test_a_new_kind_takes_portrait_artwork_only(client, monkeypatch, w, h, ok):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    rk = _candidate('tool')
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


def test_a_late_approval_of_a_new_kind_rolls_forward(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    headers = _admin_headers(make_person)
    rk = _candidate('tool')
    try:
        _render(client, monkeypatch, rk)
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET scheduled_for = NOW() - interval '2 days' WHERE request_key = %(rk)s",
                       dict(rk=rk))
        before = datetime.now(timezone.utc)
        r = client.post(f"/admin/growth/queue/{_rows(rk)[0]['id']}/approve", json={}, headers=headers)
        assert r.status_code == 200, r.get_json()
        slot = _rows(rk)[0]['scheduled_for']
        assert slot > before and rd.slot_problem(slot, before) is None
    finally:
        _cancel(rk)


def test_dispatch_refuses_a_new_kind_past_the_known_calendar(client, monkeypatch):
    rk = _candidate('event')
    try:
        _render(client, monkeypatch, rk)
        with _publication_on(), api_tx() as tx:
            rows = _claimed(tx, rk)
            assert len(rows) == 2
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (True, '')
            monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() - timedelta(days=2))
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (False, 'calendar_unknown')
    finally:
        _cancel(rk)


def test_the_queue_shows_week_age_and_template_data(client):
    event, tool = _candidate('event'), _candidate('tool')
    slot = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET scheduled_for = %(w)s,
                             payload = '{"title": "Sukkot gathering"}'::jsonb
                       WHERE request_key = ANY(%(k)s)""", dict(w=slot, k=[event, tool]))
    try:
        rows = {(r['request_key'], r['platform']): r for r in _listed(client, '')}
        e, t = rows[(event, 'facebook')], rows[(tool, 'facebook')]
        assert e['week'] == '2027-W01' and e['age_days'] == 0 and e['created_at']
        assert e['template_data'] == {'title': 'Sukkot gathering'}
        assert 'template_data' not in t
    finally:
        _cancel(event)
        _cancel(tool)
