"""The gathering emails (TEC-1845), through the durable outbox, with an
organiser as a third kind of recipient."""
import json
from datetime import datetime, timezone

import pytest

from database import api_tx
from service.config import API_BASE_URL, WEB_BASE_URL

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')


def _event_id(slug):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()['id']


def _rows_for(campaign, slug=None, organiser_id=None):
    """The outbox rows of one campaign for one gathering's guests (or one
    organiser), so rows other tests left do not count."""
    with api_tx('read committed') as tx:
        if organiser_id is not None:
            return [dict(r) for r in tx.execute(
                'SELECT * FROM email_outbox WHERE campaign = %(c)s AND organiser_id = %(o)s ORDER BY id',
                dict(c=campaign, o=organiser_id)).fetchall()]
        return [dict(r) for r in tx.execute(
            """SELECT o.* FROM email_outbox o JOIN event_rsvp r
                   ON r.id = split_part(o.campaign_id, ':', 1)::bigint
                 JOIN event e ON e.id = r.event_id
                WHERE o.campaign = %(c)s AND e.slug = %(s)s ORDER BY o.id""",
            dict(c=campaign, s=slug)).fetchall()]


def _queue(fn, *args):
    with api_tx() as tx:
        return fn(tx, *args)


def _set_event(slug, **cols):
    with api_tx() as tx:
        tx.execute(f"UPDATE event SET {', '.join(f'{k} = %({k})s' for k in cols)} WHERE slug = %(slug)s",
                   dict(cols, slug=slug))


def test_a_visitors_rsvp_queues_the_confirm_email_to_their_lead(client, published):
    slug = published()
    client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah Okafor', email='hannah@ahavah-test.invalid', party_size=2))
    [row] = _rows_for('event_confirm', slug)
    assert row['lead_id'] is not None and row['person_id'] is None and row['exempt'] is True
    html = row['payload']['html']
    # The link is the web page, never the API's confirm route (the plan's
    # `'/rsvp/confirm/' not in html.replace(WEB_BASE_URL, '')` can never
    # hold: removing the host leaves the path).
    assert html.count(f'{WEB_BASE_URL}/rsvp/confirm/') == 1 and f'{API_BASE_URL}/rsvp/confirm' not in html
    assert 'Elm Street' not in html and 'Confirm my place' in html
    assert 'We share the address once you confirm.' in html and 'Meet in a public place' not in html
    assert row['payload']['list_unsubscribe'] is None
    assert row['payload']['subject'] == 'Confirm your place at Marriage preparation evening'


def test_sending_it_again_queues_a_second_confirm_email(client, published):
    slug = published()
    for _ in range(2):
        client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah', email='again@ahavah-test.invalid', party_size=1))
    assert [r['campaign_id'].split(':')[1] for r in _rows_for('event_confirm', slug)] == ['0', '1']


def test_the_reminder_carries_the_venue_and_the_safety_note(published, confirmed_guest):
    from service.events import mail, rsvp
    slug = published()
    g = confirmed_guest(slug)
    token = _queue(lambda tx: rsvp.reissue_token(tx, g['id']))
    assert _queue(mail.queue_reminder, g['id'], token) is not None
    [row] = _rows_for('event_reminder', slug)
    html = row['payload']['html']
    assert 'Grace Fellowship hall, 14 Elm Street, Dallas' in html and mail.SAFETY in html
    assert f'{API_BASE_URL}/rsvp/{token}/calendar.ics' in html and f'{WEB_BASE_URL}/rsvp/{token}' in html
    assert 'You are getting this because you RSVPed to a gathering on Ahavah.' in html
    assert _queue(mail.queue_reminder, g['id'], token) is None


def test_an_online_reminder_carries_the_link_and_no_safety_note(published, confirmed_guest):
    from service.events import mail, rsvp
    slug = published(mode='online', online_url='https://meet.example.com/ahavah-talk', city=None, country=None)
    g = confirmed_guest(slug)
    token = _queue(lambda tx: rsvp.reissue_token(tx, g['id']))
    _queue(mail.queue_reminder, g['id'], token)
    [row] = _rows_for('event_reminder', slug)
    html = row['payload']['html']
    assert 'https://meet.example.com/ahavah-talk' in html and mail.SAFETY not in html


def test_a_change_says_before_and_now_and_each_guest_gets_a_fresh_link(published, confirmed_guest):
    from service.events import mail, rsvp
    slug = published()
    a = confirmed_guest(slug, name='Hannah Okafor')
    b = confirmed_guest(slug, name='Lydia Cruz')
    before = dict(date='Saturday 7 November 2026', time='5pm to 9pm, Central Time', place='Dallas',
                  venue='Grace Fellowship hall, 14 Elm Street, Dallas', mode='in_person')
    after = dict(before, time='6pm to 9pm, Central Time')
    _set_event(slug, changed_at=datetime.now(timezone.utc), change_before=json.dumps(before),
               change_after=json.dumps(after))
    assert _queue(mail.queue_change, _event_id(slug)) == 2
    rows = _rows_for('event_change', slug)
    htmls = [r['payload']['html'] for r in rows]
    for html in htmls:
        assert 'Marriage preparation evening now starts at 6pm' in html
        assert '5pm to 9pm' in html and '6pm to 9pm' in html and 'Before' in html and 'Now' in html
        assert 'Everything else stays the same. Your place is still saved.' in html and mail.SAFETY in html
    assert htmls[0] != htmls[1]
    with api_tx('read committed') as tx:
        for g in (a, b):
            with pytest.raises(Exception):
                rsvp.rsvp_view(tx, g['token'])
    assert rows[0]['payload']['subject'] == 'A change to Marriage preparation evening'


def test_the_change_line_says_what_moved():
    from service.events.mail import change_line
    b = dict(date='Saturday 7 November 2026', time='6pm to 9pm, Central Time', place='Dallas',
             venue='Hall A', mode='in_person')
    assert change_line('T', b, dict(b, date='Sunday 8 November 2026')) == 'T is now on Sunday 8 November 2026'
    assert change_line('T', b, dict(b, venue='Hall B')) == 'T is now at Hall B'
    assert change_line('T', b, dict(b, mode='online', place='Online', venue=None)) == 'T is now online'
    assert change_line('T', b, dict(b, time='7.30pm to 9pm, Central Time')) == 'T now starts at 7.30pm'


def test_the_cancelled_email_quotes_the_organisers_note(published, confirmed_guest):
    from service.events import mail
    slug = published()
    confirmed_guest(slug)
    _set_event(slug, status='cancelled', cancel_note='We are sorry. The hall is closed for repairs.')
    assert _queue(mail.queue_cancelled, _event_id(slug)) == 1
    [row] = _rows_for('event_cancelled', slug)
    html = row['payload']['html']
    assert '“We are sorry. The hall is closed for repairs.”' in html and 'Grace Fellowship' in html
    assert 'Marriage preparation evening was cancelled' in html and f'{WEB_BASE_URL}/events' in html
    assert row['payload']['subject'] == 'Marriage preparation evening was cancelled'


def test_the_digest_lists_names_and_party_sizes_never_emails(published, confirmed_guest, organiser):
    from service.events import mail
    o = organiser()
    slug = published(organiser_row=o)
    confirmed_guest(slug, name='Hannah Okafor', party_size=2, share=True, email='hannah-d@ahavah-test.invalid')
    confirmed_guest(slug, name='Lydia Cruz', party_size=1)
    day = datetime.now(timezone.utc).date()
    assert _queue(mail.queue_digest, _event_id(slug), day) is not None
    [row] = _rows_for('event_digest', organiser_id=o['id'])
    html = row['payload']['html']
    assert 'Hannah Okafor' in html and '2 people' in html and 'Lydia Cruz' in html and '1 person' in html
    assert 'hannah-d@' not in html and '@ahavah-test.invalid' not in html
    assert '2 new RSVPs for Marriage preparation evening' in html and 'going</b> in total.' in html
    assert '/host/gatherings?t=' in html and row['payload']['subject'] == '2 new RSVPs for Marriage preparation evening'
    eid = _event_id(slug)
    with api_tx('read committed') as tx:
        left = tx.execute("SELECT COUNT(*) AS n FROM event_rsvp WHERE event_id = %(e)s AND digested_at IS NULL",
                          dict(e=eid)).fetchone()['n']
    assert left == 0 and _queue(mail.queue_digest, eid, day) is None


def test_the_manage_link_goes_to_the_organiser_through_the_outbox(client, organiser):
    o = organiser()
    client.post('/organisers/link', json=dict(email=o['email']))
    [row] = _rows_for('event_manage', organiser_id=o['id'])
    assert row['organiser_id'] == o['id'] and '/host/gatherings?t=' in row['payload']['html']
    assert row['person_id'] is None and row['lead_id'] is None and row['exempt'] is True
    assert row['payload']['subject'] == 'Manage your gatherings on Ahavah'
    assert 'This link works for 7 days. You can ask for a new one at any time.' in row['payload']['html']


def _drain_only(row_id):
    from service.campaigns import outbox

    class _Smtp:
        sent = []

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


def test_a_switched_off_email_is_skipped_at_send_time(published, confirmed_guest, monkeypatch):
    from service.events import mail, rsvp
    slug = published()
    g = confirmed_guest(slug)
    token = _queue(lambda tx: rsvp.reissue_token(tx, g['id']))
    row_id = _queue(mail.queue_reminder, g['id'], token)
    monkeypatch.delenv('AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED')
    state, sent = _drain_only(row_id)
    assert state == dict(state='skipped', last_error='switched_off') and sent == []


def test_an_organiser_row_is_sent(organiser):
    from service.events import mail
    from service.events.organisers import issue_link
    o = organiser()
    row_id = _queue(lambda tx: mail.queue_manage_link(tx, o['id'], issue_link(tx, o['id'])))
    state, sent = _drain_only(row_id)
    assert state['state'] == 'accepted' and sent[0]['to_addr'] == o['email']


def test_an_email_that_is_off_is_not_queued(published, confirmed_guest, monkeypatch):
    from service.events import mail
    slug = published()
    confirmed_guest(slug)
    monkeypatch.delenv('AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED')
    assert _queue(mail.queue_cancelled, _event_id(slug)) == 0 and _rows_for('event_cancelled', slug) == []


def test_names_and_titles_are_escaped_in_every_email():
    from service.events import mail
    evil = '<script>x</script>'
    view = mail.sample_view(title=evil, organiser=evil)
    before = dict(date=evil, time=evil, place=evil, venue=evil, mode='in_person')
    for subject, html in [mail.confirm_email(view, 'tok'),
                          mail.reminder_email(mail.sample_view(title=evil, organiser=evil, confirmed=True), 'tok'),
                          mail.change_email(view, 'tok', before, dict(before, time='x')),
                          mail.cancelled_email(mail.sample_view(title=evil, organiser=evil, note=evil), 'tok'),
                          mail.digest_email(mail.sample_event(title=evil), [dict(name=evil, party_size=1)], 1, 'tok'),
                          mail.manage_email('tok', note=evil)]:
        assert '<script>' not in html


def test_every_email_uses_title_images_and_no_typed_headline():
    from service.events import mail
    from tests.email_samples import SAMPLES
    names = {s['name'] for s in SAMPLES}
    assert {'event_confirm', 'event_confirm_online', 'event_reminder', 'event_reminder_online', 'event_change',
            'event_cancelled', 'event_digest', 'event_manage', 'event_approved', 'event_live'} <= names
    for s in SAMPLES:
        if s['name'].startswith('event_'):
            assert 'error' not in s, s
            assert 'e-title-light' in s['html'], s['name']
    assert {k: v[2] for k, v in mail.TITLES.items()} == dict(
        confirm=318, reminder=251, change=242, cancelled=346, digest=270, manage=315,
        join_invite=285,  # 3.9, the invitation to join (TEC-1845)
        live=242,  # round 2, 10.1, "Your / gathering / is live." (release 3)
        refused=281)  # 8.7, the refusal: the generic "A note from Ahavah." pair
