"""The one invitation to join, the day after a gathering (TEC-1845,
docs/superpowers/plans/2026-10-22-events-invite-to-join.md, Task 7).

Only to a guest who ticked "Tell me about Ahavah events and members near
me", is not a member and has not left the news mail; once per address
across all gatherings (lead_join_invite, 0076); 10:00 to 20:00 in the
gathering's own zone on the days after it ends, never inside or within 2
hours of a rest period nor past the known calendar, and not after 7 days.
News: the outbox's news rules apply at queue and again at send, and a
guest who joins after queueing is skipped member_now.
AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED is set here, not by events_live."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'join_invite_schema', 'events_live', 'no_limits')
INVITE_ENV = 'AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED'
CAMPAIGN = 'event_join_invite'
CHICAGO = ZoneInfo('America/Chicago')
BARBADOS = ZoneInfo('America/Barbados')


@pytest.fixture
def invite_on(monkeypatch):
    monkeypatch.setenv(INVITE_ENV, '1')


@pytest.fixture
def addresses():
    """Addresses the test used: their invitation records go afterwards."""
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM lead_join_invite WHERE normalized_email = ANY(%(a)s)', dict(a=made))


def _saturday(weeks_ago: int = 1) -> date:
    """A recent Saturday, so every moment the tests use is inside the
    known calendar the conftest sets (a year from today)."""
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=(today.weekday() - 5) % 7 + 7 * weeks_ago)


def _gathering(published, *, ends_local: datetime, **over) -> str:
    starts = (ends_local - timedelta(hours=3)).astimezone(timezone.utc)
    return published(starts_at=starts, ends_at=ends_local.astimezone(timezone.utc), **over)


def _guest(confirmed_guest, addresses, slug, *, ticked=True, email=None):
    email = email or f'join-invite-{uuid4().hex[:10]}@ahavah-test.invalid'
    addresses.append(email)
    g = confirmed_guest(slug, email=email)
    if ticked:
        with api_tx() as tx:
            tx.execute('UPDATE event_rsvp SET marketing_consent = TRUE WHERE id = %(i)s', dict(i=g['id']))
            tx.execute("""UPDATE lead SET marketing_consent = TRUE, consent_wording = 'events-rsvp-news-v1',
                                          consented_at = NOW()
                           WHERE id = (SELECT lead_id FROM event_rsvp WHERE id = %(i)s)""", dict(i=g['id']))
    with api_tx('read committed') as tx:
        g['lead_id'] = tx.execute('SELECT lead_id FROM event_rsvp WHERE id = %(i)s',
                                  dict(i=g['id'])).fetchone()['lead_id']
    return g


def _tick(now: datetime) -> int:
    from service.events import jobs
    with api_tx() as tx:
        return jobs.queue_join_invites(tx, now.astimezone(timezone.utc))


def _rows(*guests) -> list[dict]:
    ids = [g['lead_id'] for g in guests]
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM email_outbox WHERE campaign = %(c)s AND lead_id = ANY(%(l)s) ORDER BY id',
            dict(c=CAMPAIGN, l=ids)).fetchall()]


def _record(email: str):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM lead_join_invite WHERE normalized_email = %(e)s',
                          dict(e=email)).fetchone()


def _drain_only(row_id):
    from service.campaigns import outbox

    class _Smtp:
        sent: list = []

        def send(self, **kw):
            self.sent.append(kw)
            return 'mid'
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND id <> %(i)s""", dict(i=row_id))
    smtp = _Smtp()
    outbox.drain(api_tx, smtp, limit=5)
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT state, last_error FROM email_outbox WHERE id = %(i)s',
                               dict(i=row_id)).fetchone()), smtp.sent


def _dallas(published, sat: date | None = None) -> tuple[str, datetime]:
    sat = sat or _saturday()
    ends = datetime(sat.year, sat.month, sat.day, 22, 0, tzinfo=CHICAGO)
    return _gathering(published, ends_local=ends), ends


def _sunday_at(ends: datetime, hour: int, minute: int = 0) -> datetime:
    sun = ends.date() + timedelta(days=1)
    return datetime(sun.year, sun.month, sun.day, hour, minute, tzinfo=ends.tzinfo)


def test_off_by_default_nothing_is_queued(published, confirmed_guest, addresses, monkeypatch):
    monkeypatch.delenv(INVITE_ENV, raising=False)
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    assert _tick(_sunday_at(ends, 10)) == 0
    assert _rows(g) == [] and _record(g['email']) is None


def test_the_day_after_in_the_gatherings_own_time(published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 9))
    assert _rows(g) == []
    _tick(_sunday_at(ends, 10))
    assert len(_rows(g)) == 1
    _tick(_sunday_at(ends, 11))
    assert len(_rows(g)) == 1


def test_invite_due_reads_the_rules():
    from service.events.join import invite_due
    ends = datetime(2026, 10, 17, 22, 0, tzinfo=CHICAGO)
    tz = 'America/Chicago'
    assert not invite_due(ends, tz, datetime(2026, 10, 17, 23, 0, tzinfo=CHICAGO))  # same day
    assert not invite_due(ends, tz, datetime(2026, 10, 18, 9, 59, tzinfo=CHICAGO))
    assert invite_due(ends, tz, datetime(2026, 10, 18, 10, 0, tzinfo=CHICAGO))
    assert invite_due(ends, tz, datetime(2026, 10, 18, 19, 59, tzinfo=CHICAGO))
    assert not invite_due(ends, tz, datetime(2026, 10, 18, 20, 0, tzinfo=CHICAGO))
    assert invite_due(ends, tz, datetime(2026, 10, 24, 19, 0, tzinfo=CHICAGO))
    assert not invite_due(ends, tz, datetime(2026, 10, 24, 22, 0, tzinfo=CHICAGO) + timedelta(hours=12))


def test_only_guests_who_ticked_the_box(published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published)
    ticked = _guest(confirmed_guest, addresses, slug)
    not_ticked = _guest(confirmed_guest, addresses, slug, ticked=False)
    _tick(_sunday_at(ends, 10))
    assert len(_rows(ticked)) == 1 and _rows(not_ticked) == []


def test_never_a_member(published, confirmed_guest, make_person, addresses, invite_on):
    slug, ends = _dallas(published)
    member_address = f'join-member-{uuid4().hex[:8]}@ahavah-test.invalid'
    addresses.append(member_address)
    p = make_person(name='InviteMember', email=member_address)
    by_account = confirmed_guest(slug, person_id=p['id'], email=member_address)
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET marketing_consent = TRUE WHERE id = %(i)s', dict(i=by_account['id']))
    joined = _guest(confirmed_guest, addresses, slug)
    make_person(name='JoinedSinceRsvp', email=joined['email'])
    _tick(_sunday_at(ends, 10))
    assert _rows(joined) == [] and _record(joined['email']) is None
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM email_outbox WHERE campaign = %(c)s AND person_id = %(p)s',
                          dict(c=CAMPAIGN, p=p['id'])).fetchone() is None
    assert _record(member_address) is None


def test_never_an_unsubscribed_or_suppressed_address(published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published)
    left = _guest(confirmed_guest, addresses, slug)
    with api_tx() as tx:
        tx.execute('UPDATE lead SET unsubscribed_at = NOW() WHERE id = %(i)s', dict(i=left['lead_id']))
    suppressed = _guest(confirmed_guest, addresses, slug,
                        email=f'join-suppressed-{uuid4().hex[:8]}@example.com')
    _tick(_sunday_at(ends, 10))
    assert _rows(left, suppressed) == []
    assert _record(left['email']) is None and _record(suppressed['email']) is None


def test_never_an_unconfirmed_or_cancelled_guest_nor_a_cancelled_or_paused_gathering(
        published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published)
    unconfirmed = _guest(confirmed_guest, addresses, slug)
    cancelled = _guest(confirmed_guest, addresses, slug)
    with api_tx() as tx:
        tx.execute('UPDATE event_rsvp SET confirmed_at = NULL WHERE id = %(i)s', dict(i=unconfirmed['id']))
        tx.execute("UPDATE event_rsvp SET status = 'cancelled' WHERE id = %(i)s", dict(i=cancelled['id']))
    gone, gone_ends = _dallas(published)
    paused, _ = _dallas(published)
    at_gone = _guest(confirmed_guest, addresses, gone)
    at_paused = _guest(confirmed_guest, addresses, paused)
    with api_tx() as tx:
        tx.execute("UPDATE event SET status = 'cancelled' WHERE slug = %(s)s", dict(s=gone))
        tx.execute('UPDATE event SET paused_at = NOW() WHERE slug = %(s)s', dict(s=paused))
    _tick(_sunday_at(ends, 10))
    assert _rows(unconfirmed, cancelled, at_gone, at_paused) == []


def test_one_invitation_per_address_across_gatherings(published, confirmed_guest, addresses, invite_on):
    address = f'join-once-{uuid4().hex[:8]}@ahavah-test.invalid'
    first, ends = _dallas(published)
    second, _ = _dallas(published)
    later, later_ends = _dallas(published, _saturday() + timedelta(days=7))
    guests = [_guest(confirmed_guest, addresses, s, email=address) for s in (first, second, later)]
    _tick(_sunday_at(ends, 10))
    _tick(_sunday_at(later_ends, 10))
    assert len(_rows(*guests)) == 1
    assert _record(address) is not None


def test_two_ticks_queue_one(published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 10))
    _tick(_sunday_at(ends, 10, 30))
    assert len(_rows(g)) == 1


def test_held_before_and_during_a_rest_period(published, confirmed_guest, addresses, invite_on, monkeypatch):
    """A rest period from 17:00 Barbados time on the day after (the rest
    day is the day after next): nothing at 15:30 (inside the 2 hour
    margin), nothing inside it, one at the first allowed hour after it."""
    import service.spotlight.restdays as rd
    sat = _saturday()
    ends = datetime(sat.year, sat.month, sat.day, 21, 0, tzinfo=BARBADOS)
    slug = _gathering(published, ends_local=ends, tz='America/Barbados', tz_label='Barbados time')
    g = _guest(confirmed_guest, addresses, slug)
    monkeypatch.setattr(rd, 'REST_DAYS', (sat + timedelta(days=2),))
    sun = sat + timedelta(days=1)
    _tick(datetime(sun.year, sun.month, sun.day, 15, 30, tzinfo=BARBADOS))
    _tick(datetime(sun.year, sun.month, sun.day, 18, 0, tzinfo=BARBADOS))
    mon = sat + timedelta(days=2)
    _tick(datetime(mon.year, mon.month, mon.day, 12, 0, tzinfo=BARBADOS))
    assert _rows(g) == []
    tue = sat + timedelta(days=3)
    _tick(datetime(tue.year, tue.month, tue.day, 10, 0, tzinfo=BARBADOS))
    assert len(_rows(g)) == 1


def test_nothing_beyond_the_known_calendar(published, confirmed_guest, addresses, invite_on, monkeypatch):
    import service.spotlight.restdays as rd
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', ends.date())
    _tick(_sunday_at(ends, 10))
    assert _rows(g) == [] and _record(g['email']) is None


def test_lapsed_after_7_days(published, confirmed_guest, addresses, invite_on):
    slug, ends = _dallas(published, _saturday(2))
    g = _guest(confirmed_guest, addresses, slug)
    eighth = ends.date() + timedelta(days=8)
    _tick(datetime(eighth.year, eighth.month, eighth.day, 10, 0, tzinfo=CHICAGO))
    assert _rows(g) == []


def test_it_is_news_with_an_unsubscribe_and_list_unsubscribe(published, confirmed_guest, addresses, invite_on):
    from service.config import WEB_BASE_URL
    from service.unsubscribe import make_url
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 10))
    [row] = _rows(g)
    unsub = make_url('news', g['email'], WEB_BASE_URL)
    assert row['exempt'] is False and row['unsub_scope'] == 'news'
    assert '/u/' in unsub and unsub in row['payload']['list_unsubscribe']
    html = row['payload']['html']
    assert unsub in html and f'src=event%3A{slug}' in html
    assert 'Marriage preparation evening' in html
    assert 'title-event-join-invite' in html


def test_an_address_that_joins_after_queueing_is_skipped(published, confirmed_guest, make_person, addresses,
                                                         invite_on):
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 10))
    [row] = _rows(g)
    make_person(name='JoinedAfterQueue', email=g['email'])
    state, sent = _drain_only(row['id'])
    assert state == dict(state='skipped', last_error='member_now') and sent == []


def test_a_queued_invitation_is_sent(published, confirmed_guest, addresses, invite_on):
    # The drain reads the real clock, and drops an invitation past its 7
    # days: the gathering ended yesterday.
    row, _ = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=1), tz=_zone_at(14))
    state, sent = _drain_only(row['id'])
    assert state['state'] == 'accepted' and sent[0]['to_addr'] == row['email']


def test_switching_off_stops_what_is_queued(published, confirmed_guest, addresses, invite_on, monkeypatch):
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 10))
    [row] = _rows(g)
    monkeypatch.delenv(INVITE_ENV)
    state, _ = _drain_only(row['id'])
    assert state == dict(state='skipped', last_error='switched_off')


def test_unsubscribe_leaves_the_news_and_keeps_the_place(published, confirmed_guest, addresses, invite_on):
    """Review focus 5: leaving the news mail from the invitation's link
    stops every later news email to the address and keeps the guest's place
    at a later gathering, with its reminder."""
    from service.events import mail, rsvp
    from service.unsubscribe import stamp_unsubscribed
    address = f'join-unsub-{uuid4().hex[:8]}@ahavah-test.invalid'
    past, ends = _dallas(published)
    g_past = _guest(confirmed_guest, addresses, past, email=address)
    coming = published()
    g_coming = _guest(confirmed_guest, addresses, coming, email=address)
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'news', address)
    with api_tx() as tx:
        r = dict(tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s', dict(i=g_coming['id'])).fetchone())
        ev = dict(tx.execute('SELECT * FROM event WHERE slug = %(s)s', dict(s=coming)).fetchone())
        assert mail.queue_join_invite(tx, r, ev, _sunday_at(ends, 10)) is None
    assert _record(address) is None and _rows(g_past, g_coming) == []
    with api_tx() as tx:
        token = rsvp.reissue_token(tx, g_coming['id'])
        assert mail.queue_reminder(tx, g_coming['id'], token) is not None
        assert tx.execute('SELECT status FROM event_rsvp WHERE id = %(i)s',
                          dict(i=g_coming['id'])).fetchone()['status'] == 'going'


def test_the_title_is_escaped_and_no_venue_or_name_appears():
    from service.events import mail
    ev = mail.sample_event(title='<b>x</b> & "y"')
    subject, html_ = mail.join_invite_email(ev, 'https://ahavah.app/auth/sign-up?src=event%3Aa-b',
                                            'https://ahavah.app/u/token')
    assert '<b>x</b>' not in html_ and '&lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;' in html_
    assert 'Elm Street' not in html_ and 'Hannah' not in html_ and 'Grace Fellowship' not in html_
    assert '<h1' not in html_ and 'Join Ahavah' in html_
    online = mail.sample_online_event()
    _, html_online = mail.join_invite_email(online, 'https://ahavah.app/auth/sign-up?src=event%3Aa-b',
                                            'https://ahavah.app/u/token')
    assert 'meet.example.com' not in html_online and ', online.' not in html_online


def test_the_owner_s_approved_wording():
    # The copy pass the owner approved on 23 Oct 2026.
    from service.events import mail
    for event in (mail.sample_event(), mail.sample_online_event()):
        subject, html_ = mail.join_invite_email(event, 'https://ahavah.app/auth/sign-up?src=event%3Aa-b',
                                                'https://ahavah.app/u/token')
        assert subject == 'Meet the community on Ahavah'
        assert f"You RSVPed to <b>{event['title']}</b>." in html_
        assert 'Members get to know one another with marriage in mind, and families can take part.' in html_
        assert ('You asked to hear about gatherings and members near you, and members see both on Ahavah.'
                in html_)
        assert 'families involved' not in html_ and 'which is what you asked' not in html_


def test_the_previews_build_from_sample_data():
    from service.events import mail
    for fn in (mail.preview_join_invite, mail.preview_join_invite_online):
        subject, html_ = fn('proof@ahavah-test.invalid')
        assert subject and '/auth/sign-up?src=event%3A' in html_ and '/u/' in html_


def test_the_job_is_in_the_return_mail_cron():
    from service.cron import returnmail
    from service.events import jobs
    names = [n for n, _ in returnmail.JOBS]
    assert ('event_join_invite', jobs.queue_join_invites) in returnmail.JOBS
    assert names.index('event_join_invite') == names.index('event_digest') + 1


# ---------------------------------------------------------------------------
# Review fixes (23 Oct 2026): leaving the news is read for the address, and
# the drain reads the rest days and the 7 days again at the send.
# ---------------------------------------------------------------------------

def test_never_an_address_that_left_the_news_at_another_gathering(published, confirmed_guest, addresses,
                                                                  invite_on):
    """The unsubscribe stamped the rows the address had then. The tick at a
    later gathering is a fresh event:{slug} row with consent and a confirmed
    address, and no stamp; the address has still left the news."""
    from service.unsubscribe import stamp_unsubscribed
    address = f'join-left-{uuid4().hex[:8]}@ahavah-test.invalid'
    earlier = published()
    _guest(confirmed_guest, addresses, earlier, email=address)
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'news', address)
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug, email=address)
    from service.leads import news_refusal
    with api_tx('read committed') as tx:
        assert news_refusal(tx, g['lead_id']) is None  # the row alone would pass
    _tick(_sunday_at(ends, 10))
    assert _rows(g) == [] and _record(address) is None


def test_an_address_that_left_the_news_on_another_row_is_skipped_at_send(published, confirmed_guest, addresses,
                                                                         invite_on):
    slug, ends = _dallas(published)
    g = _guest(confirmed_guest, addresses, slug)
    _tick(_sunday_at(ends, 10))
    [row] = _rows(g)
    with api_tx() as tx:
        tx.execute("""INSERT INTO lead (email, normalized_email, source, unsubscribed_at)
                      VALUES (%(e)s, %(e)s, 'alert:visitor', NOW())""", dict(e=g['email']))
    state, sent = _drain_only(row['id'])
    assert state == dict(state='skipped', last_error='unsubscribed') and sent == []


def _queued_now(published, confirmed_guest, addresses, *, ended_ago: timedelta, tz: str = 'America/Barbados'):
    """An invitation already in the outbox for a gathering that ended
    `ended_ago` before the real clock, as a drain that fell behind finds
    it. Queued directly: when it was due is not what these tests ask."""
    from service.events import mail
    ends = datetime.now(timezone.utc) - ended_ago
    slug = _gathering(published, ends_local=ends, tz=tz, tz_label='Barbados time')
    g = _guest(confirmed_guest, addresses, slug)
    with api_tx() as tx:
        r = dict(tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s', dict(i=g['id'])).fetchone())
        ev = dict(tx.execute('SELECT * FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone())
        assert mail.queue_join_invite(tx, r, ev, datetime.now(timezone.utc)) is not None
    [row] = _rows(g)
    return row, ev


def _zone_at(hour: int) -> str:
    """A fixed-offset zone whose local hour on the real clock is `hour`,
    so a drain test does not depend on when the suite runs."""
    o = (hour - datetime.now(timezone.utc).hour + 12) % 24 - 12
    return 'Etc/GMT' if o == 0 else f'Etc/GMT{-o:+d}'


def _outbox_row(row_id) -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM email_outbox WHERE id = %(i)s', dict(i=row_id)).fetchone())


def test_a_late_drain_inside_a_rest_period_holds_it_until_the_first_allowed_hour(
        published, confirmed_guest, addresses, invite_on, monkeypatch):
    """Queued before a rest period, drained inside it (the cron was down
    for a deploy, say): not sent, not dropped. It waits for the first hour
    the job itself would have queued it, 10:00 in the gathering's zone on
    the day the rest period ends at midnight, and has spent no attempt."""
    import service.spotlight.restdays as rd
    row, ev = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=1))
    today = datetime.now(timezone.utc).astimezone(BARBADOS).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (today, today + timedelta(days=1)))
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='queued', last_error='rest_day')
    after = _outbox_row(row['id'])
    free = today + timedelta(days=2)
    assert after['next_attempt_at'] == datetime(free.year, free.month, free.day, 10, 0, tzinfo=BARBADOS)
    assert after['attempts'] == 0
    assert _record(after['email']) is not None


def test_a_late_drain_beyond_the_known_calendar_holds_it(published, confirmed_guest, addresses, invite_on,
                                                         monkeypatch):
    """Past KNOWN_THROUGH the day may be a rest day nobody has entered: it
    waits, and looks again within the hour, so a calendar extended inside
    the 7 days lets it go."""
    import service.spotlight.restdays as rd
    row, _ = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=1), tz=_zone_at(14))
    today = datetime.now(timezone.utc).astimezone(BARBADOS).date()
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', today - timedelta(days=1))
    before = datetime.now(timezone.utc)
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='queued', last_error='unknown')
    held = _outbox_row(row['id'])['next_attempt_at']
    assert before < held <= datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', today + timedelta(days=30))
    with api_tx() as tx:
        tx.execute('UPDATE email_outbox SET next_attempt_at = NOW() WHERE id = %(i)s', dict(i=row['id']))
    state, sent = _drain_only(row['id'])
    assert state['state'] == 'accepted' and len(sent) == 1


def test_a_hold_never_reaches_past_the_7_days(published, confirmed_guest, addresses, invite_on, monkeypatch):
    """A rest period that runs past the end of the window: held until the
    window closes, then dropped there, never sent late."""
    import service.spotlight.restdays as rd
    row, ev = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=6, hours=20))
    today = datetime.now(timezone.utc).astimezone(BARBADOS).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (today, today + timedelta(days=1)))
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='queued', last_error='rest_day')
    assert _outbox_row(row['id'])['next_attempt_at'] == ev['ends_at'] + timedelta(days=7)


def test_an_invitation_drained_after_its_7_days_is_dropped(published, confirmed_guest, addresses, invite_on):
    row, _ = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=7, hours=1))
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='skipped', last_error='lapsed')
    assert _record(row['email']) is not None  # the address had its one invitation


# ---------------------------------------------------------------------------
# At the send: the hours (Owner decision 3) and the gathering's and the
# RSVP's state, read again.
# ---------------------------------------------------------------------------

def test_invite_hold_keeps_to_the_hours():
    from service.events.join import invite_hold
    ends = datetime(2026, 10, 17, 22, 0, tzinfo=CHICAGO)
    tz = 'America/Chicago'
    assert invite_hold(ends, tz, datetime(2026, 10, 18, 12, 0, tzinfo=CHICAGO)) is None
    assert invite_hold(ends, tz, datetime(2026, 10, 18, 7, 30, tzinfo=CHICAGO)) == (
        'out_of_hours', datetime(2026, 10, 18, 10, 0, tzinfo=CHICAGO))
    assert invite_hold(ends, tz, datetime(2026, 10, 18, 20, 0, tzinfo=CHICAGO)) == (
        'out_of_hours', datetime(2026, 10, 19, 10, 0, tzinfo=CHICAGO))
    # The last evening of the window: never past it, where the drain drops it.
    assert invite_hold(ends, tz, datetime(2026, 10, 24, 20, 30, tzinfo=CHICAGO)) == (
        'out_of_hours', ends + timedelta(days=7))


def test_a_drain_outside_the_hours_holds_it_until_10_in_the_gatherings_zone(
        published, confirmed_guest, addresses, invite_on):
    """Queued in the day, drained at 03:00 gathering time (the cron fell
    behind): held, no attempt spent, until 10:00 that day in the
    gathering's zone."""
    tz = _zone_at(3)
    row, _ = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=1), tz=tz)
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='queued', last_error='out_of_hours')
    after = _outbox_row(row['id'])
    local = datetime.now(timezone.utc).astimezone(ZoneInfo(tz))
    assert after['next_attempt_at'] == local.replace(hour=10, minute=0, second=0, microsecond=0)
    assert after['attempts'] == 0


@pytest.mark.parametrize('change, reason', [
    ("UPDATE event SET status = 'cancelled', cancelled_at = NOW() WHERE id = %(e)s", 'cancelled'),
    ('UPDATE event SET paused_at = NOW() WHERE id = %(e)s', 'withdrawn'),
    ("UPDATE event SET status = 'draft' WHERE id = %(e)s", 'withdrawn'),
    ('DELETE FROM event WHERE id = %(e)s', 'withdrawn'),
    ("UPDATE event_rsvp SET status = 'cancelled', cancelled_at = NOW() WHERE event_id = %(e)s", 'cancelled'),
    ("""UPDATE event_rsvp SET name = NULL, email = NULL, normalized_email = NULL, token_hash = NULL,
                              erased_at = NOW() WHERE event_id = %(e)s""", 'withdrawn'),
])
def test_a_gathering_or_place_that_ended_since_queueing_is_skipped(published, confirmed_guest, addresses,
                                                                    invite_on, change, reason):
    row, ev = _queued_now(published, confirmed_guest, addresses, ended_ago=timedelta(days=1), tz=_zone_at(14))
    with api_tx() as tx:
        tx.execute(change, dict(e=ev['id']))
    state, sent = _drain_only(row['id'])
    assert sent == [] and state == dict(state='skipped', last_error=reason)
