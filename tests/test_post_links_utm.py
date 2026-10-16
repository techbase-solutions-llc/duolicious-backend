"""Every post link carries UTM tags (growth spec, Scheduler; TEC-1845).

utm_campaign is the post's kind and utm_content its slug, set when the link
is minted. utm_source is the platform the click came from, added at the
redirect, because one link key is shared by both platform rows. First-touch
capture on the web then credits the post as utm:{source}/{kind}.
"""
from __future__ import annotations

import re
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import post_target_url, valid_target_path, with_utm_source
from service.config import WEB_BASE_URL
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('growth_schema')

BASE = WEB_BASE_URL.rstrip('/')


def _post(kind='brand', **kw) -> tuple[str, str, dict]:
    slug = f'utm-{uuid4().hex[:8]}'
    with api_tx() as tx:
        rk = create_candidate(tx, kind=kind, subject_person_id=None, caption='A caption.',
                              created_by='t', request_key=f'{kind}:{slug}', **kw)
        target = tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                            dict(k=f'post:{rk}')).fetchone()['target_url']
        captions = {r['platform']: r['caption'] for r in tx.execute(
            'SELECT platform, caption FROM publishing_queue WHERE request_key = %(rk)s',
            dict(rk=rk)).fetchall()}
    return slug, target, captions


def _cancel_all(prefix: str) -> None:
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'cancelled' WHERE request_key LIKE %(p)s",
                   dict(p=f'{prefix}%'))


def _key(facebook_caption: str) -> str:
    return re.search(r'/s/([A-Za-z0-9_-]+)\?p=facebook', facebook_caption).group(1)


def test_a_post_link_lands_on_its_page_tagged_with_its_kind_and_slug():
    slug, target, _ = _post()
    try:
        assert target == f'{BASE}/?utm_campaign=brand&utm_content={slug}'
    finally:
        _cancel_all(f'brand:{slug}')


def test_a_path_and_content_can_be_chosen():
    slug, target, _ = _post(kind='tool', target_path='/together', utm_content='game')
    try:
        assert target == f'{BASE}/together?utm_campaign=tool&utm_content=game'
    finally:
        _cancel_all(f'tool:{slug}')


def test_a_click_from_facebook_names_the_source_first(client):
    slug, _, captions = _post()
    try:
        r = client.get(f"/s/{_key(captions['facebook'])}?p=facebook")
        assert r.status_code == 302
        assert r.headers['Location'] == (
            f'{BASE}/?utm_source=facebook&utm_campaign=brand&utm_content={slug}')
    finally:
        _cancel_all(f'brand:{slug}')


def test_a_click_with_no_or_an_unknown_platform_adds_no_source(client):
    slug, target, captions = _post()
    key = _key(captions['facebook'])
    try:
        for query in ('', '?p=tiktok', '?p='):
            r = client.get(f'/s/{key}{query}')
            assert r.status_code == 302 and r.headers['Location'] == target, query
    finally:
        _cancel_all(f'brand:{slug}')


def test_an_email_link_is_never_tagged(client, make_campaign_link):
    r = client.get(f'/s/{make_campaign_link()}?p=facebook')
    assert r.status_code == 302 and r.headers['Location'] == f'{BASE}/discover'


def test_instagram_rows_still_carry_no_link():
    slug, _, captions = _post()
    try:
        assert '/s/' not in captions['instagram'] and 'http' not in captions['instagram']
        assert '/s/' in captions['facebook']
    finally:
        _cancel_all(f'brand:{slug}')


@pytest.mark.parametrize('path', ['https://evil.example/', '//evil.example', 'together',
                                  '/a b', '/x?y=1', '', None, 7])
def test_a_target_that_is_not_a_path_on_the_site_is_refused(path):
    assert valid_target_path(path) is False
    with pytest.raises(ValueError, match='bad_target_path'):
        post_target_url(path, 'brand', 'x')
    with pytest.raises(ValueError, match='bad_target_path'):
        with api_tx() as tx:
            create_candidate(tx, kind='brand', subject_person_id=None, caption='c',
                             created_by='t', target_path=path)


def test_a_source_already_on_the_target_is_kept():
    tagged = f'{BASE}/?utm_source=newsletter&utm_campaign=brand&utm_content=x'
    assert with_utm_source(tagged, 'facebook') == tagged
