"""The 3-day gap counts question pushes (TEC-1845, owner decision 12).

`question` and `match_question` join the gap campaigns, and the gap reads
push_send_log for them, since a push has no outbox row. The cost the spec
names: the weekly emails that respect the gap (one_photo, profile_views,
likes_waiting) are skipped for a member who had a question push in the last
3 days. Other pushes still do not count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import one_photo_nudge
from service.campaigns import held

pytestmark = pytest.mark.usefixtures('questions_schema')

TUESDAY = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)


def _push(pid, campaign, days_ago):
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, %(c)s, %(cid)s, NOW() - make_interval(days => %(d)s))""",
                   dict(p=pid, c=campaign, cid=f'gap-{uuid4().hex[:8]}', d=days_ago))


def _gap(pid) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute(f"SELECT {held.nudged_recently_sql('%(p)s')} AS g", dict(p=pid)).fetchone()['g']


def test_a_question_push_in_the_last_3_days_counts(make_person):
    p = make_person(name='GapQuestion')
    _push(p['id'], 'question', 2)
    assert _gap(p['id']) is True


def test_a_silent_match_push_counts_too(make_person):
    p = make_person(name='GapMatch')
    _push(p['id'], 'match_question', 1)
    assert _gap(p['id']) is True


def test_an_older_question_push_does_not_count(make_person):
    p = make_person(name='GapOld')
    _push(p['id'], 'question', 4)
    assert _gap(p['id']) is False


def test_other_pushes_still_do_not_count(make_person):
    p = make_person(name='GapOther')
    _push(p['id'], 'match_reminder', 1)
    assert _gap(p['id']) is False


def test_the_tuesday_photo_email_waits_after_a_question_push(make_person, add_photo, monkeypatch):
    monkeypatch.setenv('AHAVAH_ONE_PHOTO_NUDGE_ENABLED', '1')
    pushed = make_person(name='GapPhotoA', email=f'gap-a-{uuid4().hex[:8]}@ahavah-test.invalid')
    quiet = make_person(name='GapPhotoB', email=f'gap-b-{uuid4().hex[:8]}@ahavah-test.invalid')
    for p in (pushed, quiet):
        add_photo(p['id'], position=1)
    _push(pushed['id'], 'question', 2)
    with api_tx() as tx:
        one_photo_nudge.queue_due(tx, TUESDAY)
    with api_tx('read committed') as tx:
        queued = {r['person_id'] for r in tx.execute(
            "SELECT person_id FROM email_outbox WHERE campaign = 'one_photo' AND person_id = ANY(%(i)s)",
            dict(i=[pushed['id'], quiet['id']])).fetchall()}
    assert queued == {quiet['id']}
