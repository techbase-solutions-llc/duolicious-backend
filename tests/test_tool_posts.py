"""A tool post: the monthly game or checklist promotion (TEC-1845).

Growth spec, Scheduler: "a monthly game or checklist promotion from static
Claude Design artwork, through the existing brand path". It is a brand post
with its own kind, so the Sources table and the queue can tell them apart,
and its link lands on the tools page.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.config import WEB_BASE_URL

pytestmark = pytest.mark.usefixtures('growth_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}


def _slug() -> str:
    return f'test-{secrets.token_hex(4)}'


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()


def _post(client, **body):
    payload = dict(slug=_slug(), caption='How well do you fit with someone?',
                   scheduled_for=_soon(), **body)
    return client.post('/admin/growth/brand', json=payload, headers=H), payload['slug']


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT kind, status FROM publishing_queue WHERE request_key = %(rk)s',
            dict(rk=rk)).fetchall()]


def _target(rk):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                          dict(k=f'post:{rk}')).fetchone()['target_url']


def _cancel(rk):
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'cancelled' WHERE request_key = %(rk)s",
                   dict(rk=rk))


def test_a_tool_post_is_queued_with_its_own_kind_and_landing_page(client):
    r, slug = _post(client, kind='tool', target_path='/together')
    assert r.status_code == 200, r.get_json()
    rk = r.get_json()['request_key']
    try:
        assert rk == f'tool:{slug}'
        assert {(x['kind'], x['status']) for x in _rows(rk)} == {('tool', 'awaiting_render')}
        assert _target(rk) == (f"{WEB_BASE_URL.rstrip('/')}/together"
                               f"?utm_campaign=tool&utm_content={slug}")
    finally:
        _cancel(rk)


def test_without_a_kind_it_is_a_brand_post_as_before(client):
    r, slug = _post(client)
    rk = r.get_json()['request_key']
    try:
        assert rk == f'brand:{slug}'
        assert {x['kind'] for x in _rows(rk)} == {'brand'}
    finally:
        _cancel(rk)


def test_a_brand_and_a_tool_post_may_share_a_slug(client):
    slug = _slug()
    body = dict(slug=slug, caption='c', scheduled_for=_soon())
    a = client.post('/admin/growth/brand', json=body, headers=H).get_json()['request_key']
    b = client.post('/admin/growth/brand', json=dict(body, kind='tool'), headers=H).get_json()['request_key']
    try:
        assert (a, b) == (f'brand:{slug}', f'tool:{slug}')
    finally:
        _cancel(a)
        _cancel(b)


@pytest.mark.parametrize('extra,error', [
    (dict(kind='event'), 'bad_kind'),
    (dict(kind='prompt'), 'bad_kind'),
    (dict(kind=['tool']), 'bad_kind'),
    (dict(kind='tool', target_path='https://evil.example/'), 'bad_target_path'),
    (dict(kind='tool', target_path='/together?x=1'), 'bad_target_path'),
    (dict(kind='tool', slug='a' * 60), 'bad_slug'),
])
def test_bad_input_is_refused_before_anything_is_written(client, extra, error):
    body = dict(slug=_slug(), caption='c', scheduled_for=_soon())
    body.update(extra)
    r = client.post('/admin/growth/brand', json=body, headers=H)
    assert r.status_code == 400 and r.get_json() == dict(error=error)
