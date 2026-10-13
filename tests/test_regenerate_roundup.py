"""scripts/regenerate_roundup.py: a roundup made before staff were left out
of its count is rebuilt from the week it describes (health review, 13 Oct
2026, finding 2). The W41 roundup awaiting approval said 4 joined; 3 had."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from scripts.regenerate_roundup import regenerate_roundup
from service.config import WEB_BASE_URL
from service.spotlight.queue import create_candidate
from service.spotlight.revisions import current_revision, edit_caption
from service.spotlight.roundup import roundup_caption, roundup_totals

AS_OF = datetime.now(timezone.utc) - timedelta(days=40)


@pytest.fixture
def stale_roundup():
    """A count-only roundup in review, created 40 days ago, whose stored
    count is wrong. Cleared afterwards: queue rows first (they hold the FK
    to spotlight_revision), then the revisions and the post's link."""
    rk = f'roundup:test-{uuid.uuid4().hex[:12]}'
    with api_tx() as tx:
        true = roundup_totals(tx, as_of=AS_OF)
        wrong = dict(true, count=true['count'] + 1)
        create_candidate(tx, kind='roundup', subject_person_id=None,
                         caption=roundup_caption(wrong['count'], wrong['countries']),
                         created_by='t', request_key=rk)
        tx.execute(
            """UPDATE publishing_queue SET payload = %(p)s::jsonb, status = 'review',
                      created_at = %(t)s WHERE request_key = %(rk)s""",
            dict(p=json.dumps(dict(tiles=[], **wrong)), t=AS_OF, rk=rk))
    yield rk
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(k)s", dict(k=rk))
        tx.execute("DELETE FROM spotlight_revision WHERE request_key = %(k)s", dict(k=rk))
        tx.execute("DELETE FROM campaign_link WHERE kind = %(k)s", dict(k=f'post:{rk}'))


def _rows(rk):
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT platform, status, caption, payload, current_revision_id
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()


def test_the_count_and_caption_are_rebuilt_for_the_week_described(stale_roundup):
    rk = stale_roundup
    before = _rows(rk)
    with api_tx() as tx:
        true = roundup_totals(tx, as_of=AS_OF)
        out = regenerate_roundup(tx, rk)
        rev = current_revision(tx, rk)
    assert out['changed'] is True
    assert out['old']['count'] == true['count'] + 1
    assert out['new']['count'] == true['count']
    after = _rows(rk)
    sentence = roundup_caption(true['count'], true['countries'])
    for row in after:
        assert row['payload']['count'] == true['count']
        assert row['payload']['countries'] == true['countries']
        assert row['payload']['tiles'] == []
        # The post's one /s/ link survives, stamped with each row's platform.
        assert row['caption'].startswith(sentence + f" {WEB_BASE_URL.rstrip('/')}/s/")
        assert row['caption'].endswith(f"?p={row['platform']}")
        # Approval stays with the owner: a card in review stays in review.
        assert row['status'] == 'review'
        assert row['current_revision_id'] != before[0]['current_revision_id']
    # A new revision with no artwork yet, so the next tick draws it again.
    assert rev['revision'] == 2 and rev['asset_hash'] is None
    assert rev['caption'].startswith(sentence + ' ')


def test_a_second_run_changes_nothing(stale_roundup):
    with api_tx() as tx:
        regenerate_roundup(tx, stale_roundup)
    with api_tx() as tx:
        out = regenerate_roundup(tx, stale_roundup)
        rev = current_revision(tx, stale_roundup)
    assert out['changed'] is False
    assert rev['revision'] == 2


def test_a_dry_run_writes_nothing(stale_roundup):
    before = _rows(stale_roundup)
    with api_tx() as tx:
        out = regenerate_roundup(tx, stale_roundup, dry_run=True)
    assert out['changed'] is True and out['dry_run'] is True
    assert _rows(stale_roundup) == before


def test_a_hand_edited_caption_is_refused(stale_roundup):
    with api_tx() as tx:
        edit_caption(tx, stale_roundup, 'Our own words this week.', 't')
    before = _rows(stale_roundup)
    with pytest.raises(ValueError, match='caption_edited'):
        with api_tx() as tx:
            regenerate_roundup(tx, stale_roundup)
    assert _rows(stale_roundup) == before


@pytest.mark.parametrize('status', ['scheduled', 'published', 'cancelled'])
def test_a_roundup_past_review_is_refused(stale_roundup, status):
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = %(s)s WHERE request_key = %(rk)s",
                   dict(s=status, rk=stale_roundup))
    with pytest.raises(ValueError):
        with api_tx() as tx:
            regenerate_roundup(tx, stale_roundup)


def test_an_unknown_key_is_refused():
    with pytest.raises(ValueError, match='not_found'):
        with api_tx() as tx:
            regenerate_roundup(tx, 'roundup:1999-W01')
