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
import io
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from PIL import Image

from database import api_tx
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('carousel_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}
MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0089_carousel_slides.sql'


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
