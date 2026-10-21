"""The reminder the day before and the organiser's daily digest (TEC-1845),
held out of the owner's rest days."""
from datetime import date, datetime, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.events import jobs

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')

# Saturday 7 November 2026, 6pm in Dallas.
DALLAS = dict(starts_at='2026-11-08T00:00:00+00:00', ends_at='2026-11-08T03:00:00+00:00', tz='America/Chicago')


def _at(day, hour):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def _reminders(tx, now):
    return jobs.queue_reminders(tx, now)


def _reminder_rows(slug):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT o.campaign_id FROM email_outbox o JOIN event_rsvp r
                   ON r.id = split_part(o.campaign_id, ':', 1)::bigint
                 JOIN event e ON e.id = r.event_id
                WHERE o.campaign = 'event_reminder' AND e.slug = %(s)s ORDER BY o.id""",
            dict(s=slug)).fetchall()]


def test_the_reminder_goes_on_the_local_day_before(published, confirmed_guest):
    slug = published(**DALLAS)
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(6, 13)) == 0   # Friday 7am Dallas
        assert jobs.queue_reminders(tx, _at(6, 14)) == 1   # Friday 8am Dallas
        assert jobs.queue_reminders(tx, _at(6, 15)) == 0   # already queued
    assert len(_reminder_rows(slug)) == 1


def test_not_before_8_or_from_9pm_and_not_two_days_before(published, confirmed_guest):
    slug = published(**DALLAS)
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(5, 20)) == 0   # Thursday 2pm Dallas
        assert jobs.queue_reminders(tx, _at(7, 3)) == 0    # Friday 9pm Dallas
        assert jobs.queue_reminders(tx, _at(7, 18)) == 0   # Saturday noon, the day itself


def test_a_rest_period_holds_the_reminder_until_it_ends(published, confirmed_guest, monkeypatch):
    # Tokyo: the rest period for 5 November runs to midnight Barbados, 1pm
    # on Friday 6 November in Tokyo, the day before a Saturday 7pm gathering.
    monkeypatch.setattr(rd, 'REST_DAYS', (date(2026, 11, 5),))
    slug = published(starts_at='2026-11-07T10:00:00+00:00', ends_at='2026-11-07T13:00:00+00:00',
                     tz='Asia/Tokyo', city='Tokyo', country='Japan')
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(5, 23)) == 0   # Friday 8am Tokyo, resting
        assert jobs.queue_reminders(tx, _at(6, 3)) == 0    # noon Tokyo, resting
        assert jobs.queue_reminders(tx, _at(6, 4)) == 1    # 1pm Tokyo, the rest has ended


def test_no_reminder_when_the_whole_day_before_is_a_rest_day(published, confirmed_guest, monkeypatch):
    monkeypatch.setattr(rd, 'REST_DAYS', (date(2026, 11, 6),))
    slug = published(**DALLAS)
    confirmed_guest(slug)
    with api_tx() as tx:
        start = _at(6, 6)
        assert sum(jobs.queue_reminders(tx, start + timedelta(hours=h)) for h in range(24)) == 0


def test_a_moved_gathering_gets_a_new_reminder(published, confirmed_guest):
    slug = published(**DALLAS)
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(6, 14)) == 1
        tx.execute("""UPDATE event SET starts_at = starts_at + interval '1 day',
                                       ends_at = ends_at + interval '1 day' WHERE slug = %(s)s""", dict(s=slug))
        assert jobs.queue_reminders(tx, _at(7, 14)) == 1
    assert len({r['campaign_id'] for r in _reminder_rows(slug)}) == 2


def test_an_unconfirmed_or_cancelled_guest_gets_none(published, confirmed_guest):
    slug = published(**DALLAS)
    g = confirmed_guest(slug)
    u = confirmed_guest(slug)
    with api_tx() as tx:
        tx.execute("UPDATE event_rsvp SET status = 'cancelled' WHERE id = %(i)s", dict(i=g['id']))
        tx.execute('UPDATE event_rsvp SET confirmed_at = NULL WHERE id = %(i)s', dict(i=u['id']))
        assert jobs.queue_reminders(tx, _at(6, 14)) == 0


def test_a_cancelled_or_paused_gathering_gets_none(published, confirmed_guest):
    gone = published(status='cancelled', **DALLAS)
    paused = published(paused_at=datetime.now(timezone.utc), **DALLAS)
    for slug in (gone, paused):
        confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(6, 14)) == 0


def test_the_reminder_is_off_until_its_switch(published, confirmed_guest, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED')
    slug = published(**DALLAS)
    g = confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, _at(6, 14)) == 0
    # No link was retired for an email that never went.
    from service.events.rsvp import rsvp_view
    with api_tx('read committed') as tx:
        assert rsvp_view(tx, g['token'], now=_at(6, 14))['rsvp']['confirmed'] is True


def _digest_rows(organiser_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT campaign_id FROM email_outbox WHERE campaign = 'event_digest' AND organiser_id = %(o)s ORDER BY id",
            dict(o=organiser_id)).fetchall()]


def test_the_digest_goes_once_a_day_and_only_with_new_rsvps(published, confirmed_guest, organiser):
    o = organiser()
    slug = published(organiser_row=o)
    confirmed_guest(slug)
    now = datetime.now(timezone.utc).replace(hour=11, minute=30)
    with api_tx() as tx:
        assert jobs.queue_digests(tx, now) == 0                          # before 12:00 UTC
        assert jobs.queue_digests(tx, now.replace(hour=12)) == 1
        assert jobs.queue_digests(tx, now.replace(hour=13)) == 0         # once a day
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_digests(tx, now.replace(hour=14)) == 0         # still that day
        tomorrow = now.replace(hour=12) + timedelta(days=1)
        assert jobs.queue_digests(tx, tomorrow) == 1
        assert jobs.queue_digests(tx, tomorrow + timedelta(days=1)) == 0  # nothing new
    assert len(_digest_rows(o['id'])) == 2


def test_the_digest_skips_a_rest_day_and_carries_its_rsvps_forward(published, confirmed_guest, organiser, monkeypatch):
    o = organiser()
    slug = published(organiser_row=o)
    confirmed_guest(slug)
    confirmed_guest(slug)
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (today,))
    noon = datetime.combine(today, datetime.min.time(), timezone.utc).replace(hour=12)
    with api_tx() as tx:
        assert jobs.queue_digests(tx, noon) == 0
        assert jobs.queue_digests(tx, noon + timedelta(days=1)) == 1
    with api_tx('read committed') as tx:
        assert tx.execute("""SELECT COUNT(*) AS n FROM event_rsvp r JOIN event e ON e.id = r.event_id
                              WHERE e.slug = %(s)s AND r.digested_at IS NOT NULL""",
                          dict(s=slug)).fetchone()['n'] == 2


def test_both_jobs_are_in_the_return_mail_cron():
    from service.cron.returnmail import JOBS
    assert {'event_reminder', 'event_digest'} <= {n for n, _ in JOBS}
