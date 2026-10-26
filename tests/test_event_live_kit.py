"""The "is live" email carries the organiser share kit, and the daily guests
email a quiet "Share it again" (TEC-1845; ahavah-web "Ahavah In-app Entry
Round 2.html" screen 10, copy 19 with the 23 Oct copy pass, rows 35 to 43).

The kit follows hosting and app_entries for the organiser (the member who
made it, or its address), as every new entry does. Without it the live
email is the manage email with its note, as before. Nothing in the kit
names the venue, the call link or who is going."""
import pytest

from database import api_tx
from service.events import mail

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')

ANN_IN = ('Shalom all. Grace Fellowship is hosting Marriage preparation evening on Saturday 7 November '
          'at 6pm in Dallas. Everyone is welcome. RSVP here: '
          'https://ahavah.app/e/marriage-preparation-evening-a1b2c3?s=host')
ANN_ON = ('Shalom all. Ahavah is hosting Preparing for marriage: a talk and questions online on Thursday '
          '12 November at 7pm UK time. Join from anywhere. RSVP here: '
          'https://ahavah.app/e/preparing-for-marriage-a-talk-d4e5f6?s=host')


def _ev(**over):
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)  # 6pm Central, 7 November
    return mail.sample_event(starts_at=start.isoformat(), ends_at=(start + timedelta(hours=3)).isoformat(),
                             **over)


@pytest.fixture(autouse=True)
def _site(monkeypatch):
    monkeypatch.setattr(mail, 'WEB_BASE_URL', 'https://ahavah.app')


def test_the_announcement_in_person_and_online():
    assert mail.announcement(_ev()) == ANN_IN
    assert mail.announcement(mail.sample_online_event()) == ANN_ON


def test_the_live_email_carries_the_kit():
    subject, html = mail.live_email(_ev(), 'tok' * 11)
    assert subject == 'Marriage preparation evening is live on Ahavah'
    assert 'title-gathering-live' in html and 'alt="Your gathering is live."' in html
    assert ('People can RSVP from its page now. When they do, we email you once a day with who is new.'
            in html)
    assert 'See your gathering' in html and 'href="https://ahavah.app/e/marriage-preparation-evening-a1b2c3"' in html
    assert 'Share it' in html
    assert 'Its page: ' in html and 'https://ahavah.app/e/marriage-preparation-evening-a1b2c3?s=host' in html
    assert 'Download the story image' in html and 'Download the post image' in html
    assert '/e/marriage-preparation-evening-a1b2c3/share-image?size=story' in html
    assert '/e/marriage-preparation-evening-a1b2c3/share-image?size=feed' in html
    assert 'A short announcement for your group' in html and ANN_IN in html
    assert 'Manage your gathering' in html and mail.manage_url('tok' * 11) in html
    assert 'You are getting this because you host this gathering on Ahavah.' in html
    # Never the venue.
    assert 'Elm Street' not in html


def test_the_live_email_online_never_shows_the_call_link():
    _, html = mail.live_email(mail.sample_online_event(), 'tok' * 11)
    assert ANN_ON in html and 'meet.example.com' not in html and 'Online' in html


def test_the_title_is_escaped_everywhere():
    _, html = mail.live_email(_ev(title='<b>Feast</b> & meal', organiser=dict(name='A & B', kind='other')),
                              'tok' * 11)
    assert '<b>Feast</b>' not in html and '&lt;b&gt;Feast&lt;/b&gt; &amp; meal' in html


def test_the_digest_offers_share_it_again_only_with_the_kit():
    ev = dict(_ev(), title='Marriage preparation evening')
    rows = [dict(name='Hannah Okafor', party_size=2)]
    _, plain = mail.digest_email(ev, rows, 2, 'tok' * 11)
    _, kit = mail.digest_email(ev, rows, 2, 'tok' * 11, share=True)
    assert 'Share it again' not in plain
    assert 'Want more people to come?' in kit and 'Share it again' in kit
    assert ('/host/gatherings/marriage-preparation-evening-a1b2c3/guests?t=' + 'tok' * 11 + '&amp;share=1') in kit


def _live_row(o):
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            "SELECT payload FROM email_outbox WHERE campaign = 'event_organiser_note' AND organiser_id = %(o)s",
            dict(o=o['id'])).fetchall()]


@pytest.fixture
def create(client, event_cleanup):
    from tests.test_event_manage import draft

    def _create(o, **over):
        slug = client.post('/organiser/events', headers=o['headers'], json=draft(**over)).get_json()['slug']
        event_cleanup(slug)
        return slug
    return _create


@pytest.fixture
def approve(client, admin_headers, create):
    def _go(o):
        slug = create(o)
        client.post(f'/organiser/events/{slug}/publish', headers=o['headers'])
        assert client.post(f'/admin/events/{slug}/approve', headers=admin_headers).status_code == 200
        [row] = _live_row(o)
        return row['payload']['html']
    return _go


def test_approval_sends_the_kit_while_hosting_and_app_entries_are_on(organiser, approve, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    html = approve(organiser(approved=False))
    assert 'Download the story image' in html and 'Manage your gathering' in html


@pytest.mark.parametrize('setting', ['off', 'owner'])
def test_approval_sends_the_note_alone_while_app_entries_leaves_the_organiser_out(
        organiser, approve, monkeypatch, setting):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', setting)
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', 'someone-else@ahavah-test.invalid')
    html = approve(organiser(approved=False))
    assert 'Download the story image' not in html and 'is live.' in html


def test_the_owner_list_names_the_organisers_member(organiser, approve, make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    owner = make_person(name='Owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', str(owner['id']))
    o = organiser(approved=False)
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET member_person_id = %(p)s WHERE id = %(o)s', dict(p=owner['id'], o=o['id']))
    assert 'Download the story image' in approve(o)


def test_the_organiser_pages_say_whether_the_kit_shows(client, organiser, published, monkeypatch):
    o = organiser()
    slug = published(o)
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    assert client.get('/organiser/me', headers=o['headers']).get_json()['kit'] is True
    assert client.get(f'/organiser/events/{slug}', headers=o['headers']).get_json()['kit'] is True
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'off')
    assert client.get('/organiser/me', headers=o['headers']).get_json()['kit'] is False
    assert client.get(f'/organiser/events/{slug}', headers=o['headers']).get_json()['kit'] is False
