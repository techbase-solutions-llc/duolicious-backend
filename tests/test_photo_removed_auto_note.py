"""Photos the NSFW cron rejects can tell the member (TEC-1845 admin audit,
Medium), behind a switch that is off.

send_photo_removed had one caller, the manual Take down, so a member whose
photo the cron rejected never heard why it vanished. The cron now queues the
same note through email_outbox for each photo it moves to rejected, but only
while AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED is on. It is a new email to
members, so it stays off until the owner has seen it."""
from __future__ import annotations

import inspect
import pathlib
import secrets

import pytest

from database import api_tx
from service.campaigns.switches import SWITCHES, enabled

ENV = 'AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED'


def _scored_photo(person_id: int, status: str, score: float) -> str:
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, nsfw_score,
                                  blurhash, hash)
               VALUES (%(u)s, %(p)s,
                       (SELECT COALESCE(MAX(position), 0) + 1 FROM photo WHERE person_id = %(p)s),
                       %(s)s, %(n)s, 'testblurhash', gen_random_uuid()::text)""",
            dict(u=uuid, p=person_id, s=status, n=score))
    return uuid


def _mailable(make_person) -> dict:
    p = make_person(name='Photo Owner')
    email = f"auto-removed-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute('UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s',
                   dict(e=email, i=p['id']))
    return p


def _queued(person_id: int) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            "SELECT campaign, campaign_id, exempt FROM email_outbox WHERE person_id = %(p)s",
            dict(p=person_id)).fetchall()]


def test_the_switch_is_off_until_its_variable_is_on(monkeypatch):
    assert SWITCHES['auto_photo_removed_email'] == ENV
    monkeypatch.delenv(ENV, raising=False)
    assert enabled('auto_photo_removed_email') is False
    monkeypatch.setenv(ENV, '1')
    assert enabled('auto_photo_removed_email') is True


def test_the_compose_file_passes_it_to_the_api_and_the_cron():
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{ENV}: ${{{ENV}:-0}}') == 2


def test_nothing_is_queued_while_the_switch_is_off(make_person, monkeypatch):
    from emails.photo_removed import queue_for_automatic_rejections
    monkeypatch.delenv(ENV, raising=False)
    p = _mailable(make_person)
    uuid = _scored_photo(p['id'], 'rejected', 0.91)
    assert queue_for_automatic_rejections([uuid]) == 0
    assert _queued(p['id']) == []


def test_each_automatic_rejection_queues_one_note(make_person, monkeypatch):
    from emails.photo_removed import queue_for_automatic_rejections
    monkeypatch.setenv(ENV, '1')
    p = _mailable(make_person)
    rejected = _scored_photo(p['id'], 'rejected', 0.91)
    approved = _scored_photo(p['id'], 'approved', 0.05)
    assert queue_for_automatic_rejections([rejected, approved]) == 1
    # A second tick over the same photo queues nothing more.
    assert queue_for_automatic_rejections([rejected]) == 0
    (row,) = _queued(p['id'])
    assert row == {'campaign': 'photo_removed', 'campaign_id': f'photo_removed-{rejected}',
                   'exempt': True}


def test_a_photo_a_person_took_down_is_not_the_crons(make_person, monkeypatch):
    """The manual route mails the member itself; its photo has no score."""
    from emails.photo_removed import queue_for_automatic_rejections
    monkeypatch.setenv(ENV, '1')
    p = _mailable(make_person)
    uuid = _scored_photo(p['id'], 'rejected', None)
    assert queue_for_automatic_rejections([uuid]) == 0


def test_the_cron_hands_its_photos_over():
    import service.cron.nsfwphotorunner as cron
    assert 'queue_for_automatic_rejections' in inspect.getsource(cron.predict_nsfw_photos_once)


@pytest.fixture(autouse=True)
def _clean_outbox(make_person):
    yield
    with api_tx() as tx:
        tx.execute("DELETE FROM email_outbox WHERE campaign = 'photo_removed' "
                   "AND email LIKE 'auto-removed-%%@ahavah-test.invalid'")
