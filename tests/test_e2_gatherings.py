"""Gatherings near you in Monday's E2 (TEC-1845, gatherings in the member
emails, Task 4): up to 3 gatherings in the member's region and online,
left out when there are none, behind AHAVAH_E2_GATHERINGS_ENABLED, which
counts only while events_live and events_list are on. With the switch
off, E2 is exactly what it was.

The week is read as of a far-future `now`, with the test's gatherings just
after it, so gatherings other tests left on the shared database never show
(as in tests/test_events_near_member.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import community_weekly as cw
from emails import send_community_weekly as e2
from service.config import WEB_BASE_URL

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')

NOW = datetime(2031, 3, 3, 12, 0, tzinfo=timezone.utc)
HEADING = 'alt="Gatherings near you."'


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_GATHERINGS_ENABLED', '1')


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv('AHAVAH_E2_GATHERINGS_ENABLED', raising=False)


def _at(days: float) -> datetime:
    return NOW + timedelta(days=days)


def _online(published, **over):
    return published(**dict(dict(mode='online', city=None, country=None, title='Preparing for marriage',
                                 online_url='https://meet.example.com/e2', starts_at=_at(2)), **over))


def _row(make_person, name, country=None):
    p = make_person(name=name, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        tx.execute('UPDATE person SET country = %(c)s WHERE id = %(i)s', dict(c=country, i=p['id']))
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    return dict(person_id=p['id'], email=email, name='x', country=country,
                week=e2._week_context(now=NOW))


def _links(pid):
    with api_tx('read committed') as tx:
        return {r['key']: r['target_url'] for r in tx.execute(
            'SELECT key, target_url FROM campaign_link WHERE subject_person_id = %(p)s', dict(p=pid))}


def _gathering_links(pid):
    return {k: t for k, t in _links(pid).items() if '/events' in t or '/e/' in t}


def test_off_by_default_e2_has_no_gatherings_and_mints_no_link(make_person, published, off):
    published(starts_at=_at(1))
    _online(published)
    row = _row(make_person, 'E2GOff', 'US')
    assert row['week']['gatherings'] == {}
    _, html = e2.build_for(row)
    assert HEADING not in html and '/events' not in html
    assert _gathering_links(row['person_id']) == {}


def test_on_without_the_list_switch_there_is_still_no_block(make_person, published, on, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_LIST_ENABLED')
    published(starts_at=_at(1))
    row = _row(make_person, 'E2GNoList', 'US')
    _, html = e2.build_for(row)
    assert HEADING not in html and _gathering_links(row['person_id']) == {}


def test_on_a_member_in_north_america_sees_dallas_and_online_not_london(make_person, published, on):
    published(starts_at=_at(1), title='Dallas evening', city='Dallas', country='United States')
    published(starts_at=_at(1.5), title='London evening', city='London', country='United Kingdom')
    _online(published, title='An online talk')
    _, html = e2.build_for(_row(make_person, 'E2GNA', 'BB'))
    assert HEADING in html and 'Dallas evening' in html and 'An online talk' in html
    assert 'London evening' not in html and 'Dallas, United States' in html and '>Online<' in html
    assert 'See all gatherings' in html
    assert 'Nothing near you yet' not in html
    assert "New members, gatherings near you and this week&#x27;s spotlight." in html or \
        "New members, gatherings near you and this week's spotlight." in html


def test_on_a_member_with_no_gatherings_gets_no_block(make_person, published, on, monkeypatch):
    published(starts_at=_at(1), city='London', country='United Kingdom')
    row = _row(make_person, 'E2GNone', 'US')
    _, html_on = e2.build_for(row)
    monkeypatch.delenv('AHAVAH_E2_GATHERINGS_ENABLED')
    _, html_off = e2.build_for(dict(row, week=e2._week_context(now=NOW)))
    assert HEADING not in html_on
    # The links differ by key only; the email is otherwise the off email.
    import re
    strip = lambda h: re.sub(r'/s/[A-Za-z0-9_-]+', '/s/KEY', h)
    assert strip(html_on) == strip(html_off)
    assert _gathering_links(row['person_id']) == {}


def test_on_every_card_online_says_nothing_near_yet(make_person, published, on):
    _online(published, title='An online talk')
    published(starts_at=_at(1), city='London', country='United Kingdom')
    _, html = e2.build_for(_row(make_person, 'E2GOnline', 'US'))
    assert 'Nothing near you yet. These are online.' in html and 'An online talk' in html


def test_a_member_with_no_country_sees_online_only_and_no_line(make_person, published, on):
    published(starts_at=_at(1), title='Dallas evening')
    _online(published, title='An online talk')
    row = _row(make_person, 'E2GNoCountry', None)
    _, html = e2.build_for(row)
    assert 'An online talk' in html and 'Dallas evening' not in html
    assert 'Nothing near you yet' not in html
    assert any(t == f'{WEB_BASE_URL}/events' for t in _links(row['person_id']).values())


def test_the_personal_e2_carries_it_too(make_person, published, on, monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_PERSONAL_ENABLED', '1')
    published(starts_at=_at(1), title='Dallas evening')
    _, html = e2.build_for(_row(make_person, 'E2GPersonal', 'US'))
    assert HEADING in html and 'Dallas evening' in html


def test_the_links_are_campaign_links_to_the_page_and_the_list(make_person, published, on):
    dallas = published(starts_at=_at(1))
    talk = _online(published)
    row = _row(make_person, 'E2GLinks', 'US')
    _, html = e2.build_for(row)
    links = _gathering_links(row['person_id'])
    assert sorted(links.values()) == sorted([f'{WEB_BASE_URL}/e/{dallas}', f'{WEB_BASE_URL}/e/{talk}',
                                             f'{WEB_BASE_URL}/events?region=north-america'])
    for key in links:
        assert f'/s/{key}' in html
    assert f'/e/{dallas}' not in html and '/events?region' not in html


def test_gathering_text_is_escaped(make_person, published, organiser, on):
    host = organiser(name='A & B "Assembly"')
    published(organiser_row=host, starts_at=_at(1), title='Evening <script>"x"</script>',
              city='Dallas <b>', country='United States')
    _, html = e2.build_for(_row(make_person, 'E2GEsc', 'US'))
    assert '<script>' not in html and '<b>' not in html
    assert 'Evening &lt;script&gt;&quot;x&quot;&lt;/script&gt;' in html
    assert 'A &amp; B &quot;Assembly&quot;' in html


def test_a_bad_gathering_drops_its_card_not_the_send(make_person, published, on, capsys):
    published(starts_at=_at(1), title='Broken zone evening', tz='Not/AZone')
    published(starts_at=_at(2), title='Dallas evening')
    _, html = e2.build_for(_row(make_person, 'E2GBad', 'US'))
    assert 'Dallas evening' in html and 'Broken zone evening' not in html
    assert 'dropping gathering' in capsys.readouterr().out


def test_the_week_lists_are_read_once_per_run(on, monkeypatch):
    from service.events import public
    calls = []
    monkeypatch.setattr(public, 'gatherings_for_members',
                        lambda tx, **kw: calls.append(kw) or {None: []})
    rows = e2.recipients()
    assert len(calls) == 1
    assert rows and all('country' in r for r in rows)
    assert all(r['week'] is rows[0]['week'] for r in rows)


def test_off_the_email_is_unchanged():
    args = ([dict(first_name='Rivka', country='US')], 58, None, 'https://ahavah.app/discover',
            'https://ahavah.app/u/x')
    plain = cw.community_weekly_html(*args)
    assert cw.community_weekly_html(*args, gatherings=None) == plain
    assert cw.community_weekly_html(*args, gatherings=[], gatherings_online_only=True,
                                    gatherings_see_all_url='https://ahavah.app/events') == plain
    assert "New members, community size, and this week's spotlight." in plain or \
        "New members, community size, and this week&#x27;s spotlight." in plain


def test_the_block_sits_after_the_community_line_and_before_the_button():
    html = cw.community_weekly_html(
        [], 58, None, 'https://ahavah.app/discover', 'https://ahavah.app/u/x',
        gatherings=e2.SAMPLE_GATHERINGS, gatherings_see_all_url='https://ahavah.app/events',
        gathering_url=lambda slug: f'https://ahavah.app/e/{slug}')
    community, heading, button = (html.index('members</strong> across borders'), html.index(HEADING),
                                  html.index('Open Discover'))
    assert community < heading < button


def test_no_typed_headline_in_the_block():
    import re
    block = cw._gatherings_block(e2.SAMPLE_GATHERINGS, True, 'https://ahavah.app/events',
                                 lambda slug: f'https://ahavah.app/e/{slug}')
    assert not re.search(r'<h[1-4]\b|font-size:\s*(2\d|[3-9]\d)px', block, re.I)
    assert 'subhead-gatherings-near.png' in block and 'subhead-gatherings-near-wht.png' in block


def test_the_block_follows_the_returned_design():
    """W.1 of Ahavah Gatherings in Member Emails.html: the subhead image at
    its natural 181 px, the date tile with the day at 18 px, a hairline card
    per gathering and "See all gatherings" padded to a 44 px tap area."""
    from emails.base import ASSETS_DIR
    block = cw._gatherings_block(e2.SAMPLE_GATHERINGS, False, 'https://ahavah.app/events',
                                 lambda slug: f'https://ahavah.app/e/{slug}')
    assert 'width="181"' in block and 'max-width:181px' in block
    assert (ASSETS_DIR / 'subhead-gatherings-near.png').is_file()
    assert (ASSETS_DIR / 'subhead-gatherings-near-wht.png').is_file()
    assert 'font-size:18px' in block and 'text-transform:uppercase' in block
    assert block.count('border:1px solid') == len(e2.SAMPLE_GATHERINGS)
    see_all = block[block.index('See all gatherings') - 400:block.index('See all gatherings')]
    assert 'padding:12px 0' in see_all and 'line-height:20px' in see_all
    assert 'PENDING DESIGN' not in open(cw.__file__, encoding='utf-8').read()


def test_the_online_sample_is_w3():
    """W.3: every card online, the line above them."""
    block = cw._gatherings_block(e2.SAMPLE_GATHERINGS_ONLINE, True, 'https://ahavah.app/events',
                                 lambda slug: f'https://ahavah.app/e/{slug}')
    assert block.index('Nothing near you yet. These are online.') < block.index('Preparing for marriage')
    assert 'Reading Ruth together: a study for singles' in block and block.count('>Online<') == 2


def test_the_proof_shows_three_gatherings_and_writes_nothing():
    def counts():
        with api_tx('read committed') as tx:
            return (tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n'],
                    tx.execute('SELECT count(*) AS n FROM email_outbox').fetchone()['n'])
    before = counts()
    subject, html = e2.preview_gatherings('owner@example.org')
    assert counts() == before and subject == 'This week on Ahavah'
    for title in ('Marriage preparation evening', 'Fellowship meal for singles',
                  'Sabbath afternoon study and tea'):
        assert title in html
    assert html.count('Ahavah will be there') == 1
    assert f'{WEB_BASE_URL}/events?region=north-america' in html


def test_the_proof_fits_a_phone():
    """Until Task 6 gives the section its rows in tests/email_samples.py,
    the phone check's own rules, run on the proof."""
    import re
    from tests.test_email_renders_on_a_phone import _HEADLINE, _Wide
    _, html = e2.preview_gatherings('owner@example.org')
    wide = _Wide()
    wide.feed(html)
    assert not wide.problems
    assert not _HEADLINE.search(html)
    body = html.split('</head>', 1)[1]
    assert not [px for px in re.findall(r'font-size:\s*(\d+)px', body) if int(px) < 10]
