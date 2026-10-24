"""The member welcome's mention of gatherings (TEC-1845, gatherings in the
member emails, Task 5), from M.1 of Ahavah Gatherings in Member
Emails.html: the subhead "Gather with the community.", 2 lines and "See
gatherings near you", linking to /events in the member's region. Behind
AHAVAH_WELCOME_GATHERINGS_ENABLED, which counts only while events_live and
events_list are on. Off, the welcome is exactly what it was."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import member_welcome as mw
from service.config import WEB_BASE_URL

pytestmark = pytest.mark.usefixtures('events_live')

HEADING = 'alt="Gather with the community."'
UNTIL = datetime(2027, 4, 20, tzinfo=timezone.utc)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_WELCOME_GATHERINGS_ENABLED', '1')


def _granted(make_person, name, country=None):
    p = make_person(name=name)
    email = f"{name.lower()}-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      subscription_expires_at = NOW() + interval '180 days',
                      referral_code = %(c)s, country = %(country)s
                WHERE id = %(i)s""",
            dict(i=p['id'], e=email, c=f"G{p['id']}", country=country))
    return p['id'], email


def _queued_html(pid):
    with api_tx('read committed') as tx:
        rows = tx.execute("SELECT payload FROM email_outbox WHERE person_id = %(p)s AND campaign = 'welcome'",
                          dict(p=pid)).fetchall()
    assert len(rows) == 1
    payload = rows[0]['payload']
    return (payload if isinstance(payload, dict) else json.loads(payload))['html']


def _links(pid):
    with api_tx('read committed') as tx:
        return {r['key']: (r['kind'], r['target_url']) for r in tx.execute(
            "SELECT key, kind, target_url FROM campaign_link WHERE subject_person_id = %(p)s",
            dict(p=pid))}


def _plain():
    return mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x')


def test_off_by_default_the_welcome_is_unchanged(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_WELCOME_GATHERINGS_ENABLED', raising=False)
    assert mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                  events_url=None) == _plain()
    pid, email = _granted(make_person, 'WelGOff', 'US')
    assert mw.send_member_welcome(email) is True
    html = _queued_html(pid)
    assert HEADING not in html and 'See gatherings near you' not in html
    assert _links(pid) == {}


def test_on_without_the_list_switch_there_is_no_mention(make_person, on, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_LIST_ENABLED')
    pid, email = _granted(make_person, 'WelGNoList', 'US')
    assert mw.send_member_welcome(email) is True
    assert HEADING not in _queued_html(pid) and _links(pid) == {}


def test_on_the_mention_links_to_the_list_in_the_members_region(make_person, on):
    pid, email = _granted(make_person, 'WelGBB', 'BB')
    assert mw.send_member_welcome(email) is True
    html = _queued_html(pid)
    assert HEADING in html and 'See gatherings near you' in html
    links = _links(pid)
    assert list(links.values()) == [('welcome', f'{WEB_BASE_URL}/events?region=north-america')]
    key = next(iter(links))
    assert f'/s/{key}' in html and '/events?region' not in html


def test_a_member_with_no_country_gets_the_list_of_their_devices_region(make_person, on):
    """GE-4: /events has no all-regions view. With no ?region= the page
    picks the region from the device's time zone, else North America
    (ahavah-web events-list.tsx), so the link carries no region. Owner
    decision 4 said "the whole list"; the plan records it for him to
    restate."""
    pid, email = _granted(make_person, 'WelGNone', None)
    assert mw.send_member_welcome(email) is True
    assert list(_links(pid).values()) == [('welcome', f'{WEB_BASE_URL}/events')]


def test_still_one_welcome_per_member(make_person, on):
    pid, email = _granted(make_person, 'WelGOnce', 'US')
    assert mw.send_member_welcome(email) is True
    assert mw.send_member_welcome(email) is False
    _queued_html(pid)


def test_the_mention_follows_the_returned_design():
    """M.1: after the existing welcome content, the subhead image at its
    natural 252 px, the 2 new lines at the body's 17 px and the link padded to 44 px."""
    from emails.base import ASSETS_DIR
    html = mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                  events_url='https://ahavah.app/events?region=europe', online_listed=True)
    assert (ASSETS_DIR / 'subhead-gather-community.png').is_file()
    assert (ASSETS_DIR / 'subhead-gather-community-wht.png').is_file()
    assert 'subhead-gather-community' in html and 'width="252"' in html
    tip, heading = html.index('Tip: members who add photos'), html.index(HEADING)
    lists = html.index('Ahavah lists gatherings in person and online, hosted by assemblies, '
                       'fellowship leaders, ministries and Ahavah itself.')
    online = html.index('Online gatherings are open to you wherever you live.')
    link = html.index('See gatherings near you')
    assert tip < heading < lists < online < link
    assert 'href="https://ahavah.app/events?region=europe"' in html
    before = html[link - 400:link]
    assert 'padding:12px 0' in before and 'line-height:20px' in before
    assert not re.search(r'<h[1-4]\b', html)


def test_the_proof_writes_nothing():
    def counts():
        with api_tx('read committed') as tx:
            return (tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n'],
                    tx.execute('SELECT count(*) AS n FROM email_outbox').fetchone()['n'])
    before = counts()
    subject, html = mw.preview_welcome_gatherings('owner@example.org')
    assert counts() == before and subject == mw.SUBJECT
    assert HEADING in html and f'{WEB_BASE_URL}/events?region=north-america' in html


# ---------------------------------------------------------------------------
# Review fixes and the owner's wording (23 Oct 2026).

LISTS = ('Ahavah lists gatherings in person and online, hosted by assemblies, fellowship leaders, '
         'ministries and Ahavah itself.')
ONLINE = 'Online gatherings are open to you wherever you live.'


def test_the_owners_wording_for_the_first_line():
    """Copy pass 23 Oct, file 20 row 4, approved by the owner."""
    html = mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                  events_url='https://ahavah.app/events?region=europe')
    assert LISTS in html and 'for believers' not in html


def test_the_online_line_shows_only_while_an_online_gathering_is_listed():
    """Claim 9: the line is true only while an online gathering is listed."""
    url = 'https://ahavah.app/events?region=europe'
    with_line = mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                       events_url=url, online_listed=True)
    without = mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                     events_url=url, online_listed=False)
    assert ONLINE in with_line and ONLINE not in without
    assert LISTS in without


def test_the_send_reads_whether_an_online_gathering_is_listed(make_person, on, monkeypatch):
    from service.events import public
    monkeypatch.setattr(public, 'online_listed', lambda tx, now: False)
    pid, email = _granted(make_person, 'WelGNoOnline', 'US')
    assert mw.send_member_welcome(email) is True
    html = _queued_html(pid)
    assert HEADING in html and ONLINE not in html
    monkeypatch.setattr(public, 'online_listed', lambda tx, now: True)
    pid, email = _granted(make_person, 'WelGOnline', 'US')
    assert mw.send_member_welcome(email) is True
    assert ONLINE in _queued_html(pid)


@pytest.mark.usefixtures('events_schema')
def test_online_listed_counts_only_a_visible_online_gathering(published):
    from datetime import timedelta
    from service.events import public
    far = datetime(2033, 6, 1, tzinfo=timezone.utc)
    with api_tx('read committed') as tx:
        assert public.online_listed(tx, now=far) is False
    published(starts_at=far + timedelta(days=2), title='Far Dallas evening')
    with api_tx('read committed') as tx:
        assert public.online_listed(tx, now=far) is False
    published(mode='online', city=None, country=None, starts_at=far + timedelta(days=3), title='Far talk')
    with api_tx('read committed') as tx:
        assert public.online_listed(tx, now=far) is True


def test_the_lines_are_body_size_and_the_link_turns_light_in_dark_mode():
    """The 15 px lines were 10 px on a phone; at the body's 17 px they are
    12 px there. GE-1: the link takes e-link, #BC96FF in dark clients."""
    html = mw.member_welcome_html(UNTIL, 'https://ahavah.app/i/CODE', 'https://ahavah.app/u/x',
                                  events_url='https://ahavah.app/events?region=europe')
    line = html[html.index(LISTS) - 300:html.index(LISTS)]
    assert 'class="fs17 e-strong"' in line
    link = html[html.index('See gatherings near you') - 300:html.index('See gatherings near you')]
    assert 'e-link' in link[link.rindex('<a '):]


def test_a_repeat_welcome_mints_no_second_link(make_person, on):
    """A member already welcomed gets no new campaign link from a repeat
    call (send_member_welcome.py --send loops a window)."""
    pid, email = _granted(make_person, 'WelGRepeat', 'US')
    assert mw.send_member_welcome(email) is True
    assert len(_links(pid)) == 1
    assert mw.send_member_welcome(email) is False
    assert len(_links(pid)) == 1


def test_switching_off_strips_a_queued_mention(make_person, on, monkeypatch):
    """GE-4: at the drain, with the switch off, the mention comes out of a
    welcome already queued; the welcome itself still goes."""
    from service.campaigns import outbox
    pid, email = _granted(make_person, 'WelGKill', 'US')
    assert mw.send_member_welcome(email) is True
    html = _queued_html(pid)
    monkeypatch.delenv('AHAVAH_WELCOME_GATHERINGS_ENABLED')
    with api_tx() as tx:
        sent = outbox._send_html(tx, dict(campaign='welcome', email=email), html)
    assert HEADING not in sent and 'See gatherings near you' not in sent
    assert 'Start discovering' in sent
