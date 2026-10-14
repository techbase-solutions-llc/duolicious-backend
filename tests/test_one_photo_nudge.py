"""The one-photo nudge (finding 38): members with exactly one approved photo
are asked to add a second, held behind its own switch."""
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import one_photo_nudge as op
from service.config import WEB_BASE_URL

TUESDAY = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)   # ISO week 42


def _person(make_person, name):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid"))
    return p


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, unsub_scope, payload->>'html' AS html, payload->>'subject' AS subject
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'one_photo'""",
            dict(p=pid)).fetchall()]


def _run(now=TUESDAY):
    with api_tx() as tx:
        return op.queue_due(tx, now)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_ONE_PHOTO_NUDGE_ENABLED', '1')


def test_off_by_default(make_person, add_photo, monkeypatch):
    monkeypatch.delenv('AHAVAH_ONE_PHOTO_NUDGE_ENABLED', raising=False)
    p = _person(make_person, 'OffOne')
    add_photo(p['id'])
    assert _run() == 0 and _rows(p['id']) == []


def test_a_member_with_one_approved_photo_is_asked_once(make_person, add_photo, on):
    p = _person(make_person, 'OnePhoto')
    add_photo(p['id'])
    add_photo(p['id'], position=2, status='rejected')
    _run()
    _run()
    rows = _rows(p['id'])
    assert len(rows) == 1
    r = rows[0]
    assert r['campaign_id'] == 'one_photo-2026w42' and r['unsub_scope'] == 'campaigns'
    assert r['subject'] == 'Add a second photo to your Ahavah profile'
    assert 'title-finish-profile.png' in r['html']
    with api_tx('read committed') as tx:
        target = tx.execute("SELECT target_url FROM campaign_link WHERE kind = 'one_photo' AND subject_person_id = %(p)s",
                            dict(p=p['id'])).fetchone()['target_url']
    assert target == f'{WEB_BASE_URL}/profile/edit'


def test_not_with_two_photos_none_or_a_second_waiting(make_person, add_photo, on):
    two = _person(make_person, 'TwoPhotos')
    add_photo(two['id']); add_photo(two['id'], position=2)
    none = _person(make_person, 'NoPhotos')
    waiting = _person(make_person, 'SecondWaiting')
    add_photo(waiting['id']); add_photo(waiting['id'], position=2, status='pending')
    _run()
    for p in (two, none, waiting):
        assert _rows(p['id']) == []


def test_not_again_within_30_days_and_never_more_than_twice(make_person, add_photo, on):
    recent = _person(make_person, 'AskedRecently')
    add_photo(recent['id'])
    twice = _person(make_person, 'AskedTwice')
    add_photo(twice['id'])
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'one_photo', 'one_photo-old', NOW() - interval '10 days')""",
                   dict(p=recent['id']))
        for i, days in enumerate((90, 60)):
            tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                          VALUES (%(p)s, 'one_photo', %(c)s, NOW() - make_interval(days => %(d)s))""",
                       dict(p=twice['id'], c=f'one_photo-old{i}', d=days))
    _run()
    assert _rows(recent['id']) == [] and _rows(twice['id']) == []


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = op.preview('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert subject == 'Add a second photo to your Ahavah profile'


def _make_staff(person):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(p)s", dict(p=person['id']))


def test_never_to_staff(make_person, add_photo, on):
    staff = _person(make_person, 'StaffOnePhoto')
    add_photo(staff['id'])
    _make_staff(staff)
    _run()
    assert _rows(staff['id']) == []
