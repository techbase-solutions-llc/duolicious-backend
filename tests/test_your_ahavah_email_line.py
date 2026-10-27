"""The "Your Ahavah" line in the role emails (TEC-1845; ahavah-web Claude
Design "Ahavah Release 4 Your Ahavah.html", frames 1.6 to 1.9; copy
handoff/copy/24-release-4.md, 1.6 to 1.9).

Under the footer's own reason line, the same line in each role email:
"Everything held under this email is in Your Ahavah, where you can also
delete it.", linking to /your-ahavah. Organisers (every organiser email),
gathering guests (confirm, reminder, change, cancelled) and mentors (the
invitation). Behind its own switch, your_ahavah_email_line, which counts
only while the light sign-in is open (light_sign_in and matchmaker_live),
since the link answers 404 otherwise. Never to an address a member holds:
a member's address has a profile, and Your Ahavah offers it no delete. A
queued email keeps its HTML, so the line carries markers and the drain
takes it out when, at the send, the switch is off or the address has
joined since."""
import pathlib
from datetime import date
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns.switches import SWITCHES

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'matchmaker_schema', 'mail_allowed',
                                     'no_limits')

ENV = 'AHAVAH_YOUR_AHAVAH_EMAIL_LINE_ENABLED'
LINE = 'where you can also delete it.'
_GATES = (ENV, 'AHAVAH_LIGHT_SIGN_IN_ENABLED', 'AHAVAH_MATCHMAKER_LIVE_ENABLED')


@pytest.fixture
def line_on(monkeypatch):
    for env in _GATES:
        monkeypatch.setenv(env, '1')


def _outbox(campaign, **where):
    (col, val), = where.items()
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            f'SELECT * FROM email_outbox WHERE campaign = %(c)s AND {col} = %(v)s ORDER BY id',
            dict(c=campaign, v=val)).fetchall()]


# --- the switch ---------------------------------------------------------------

def test_the_switch_and_its_variable():
    assert SWITCHES['your_ahavah_email_line'] == ENV


def test_the_compose_file_passes_it_to_the_api_and_the_cron():
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{ENV}: ${{{ENV}:-0}}') == 2


def test_off_by_default_and_it_needs_the_light_sign_in(monkeypatch):
    from emails import your_ahavah_line as yl
    for env in _GATES:
        monkeypatch.delenv(env, raising=False)
    assert not yl.on()
    monkeypatch.setenv(ENV, '1')
    assert not yl.on()
    monkeypatch.setenv('AHAVAH_LIGHT_SIGN_IN_ENABLED', '1')
    assert not yl.on()
    monkeypatch.setenv('AHAVAH_MATCHMAKER_LIVE_ENABLED', '1')
    assert yl.on()
    monkeypatch.setenv(ENV, 'maybe')
    assert not yl.on()


# --- the line -----------------------------------------------------------------

def test_the_line_as_drawn():
    from emails import your_ahavah_line as yl
    from service.config import WEB_BASE_URL
    html = yl.block()
    assert yl.has_line(html)
    assert 'Everything held under this email is in ' in html
    assert f'href="{WEB_BASE_URL}/your-ahavah"' in html and '>Your Ahavah</a>, where you can also delete it.' in html
    # The link's tap area padded to 44 px, as drawn.
    assert 'padding:12px 0;margin:-12px 0' in html
    assert yl.strip('<p>a</p>' + html + '<p>b</p>') == '<p>a</p><p>b</p>'


def test_each_builder_carries_it_only_when_asked():
    from service.events import mail as em
    from service.matchmaker import mail as mm
    view = em.sample_view(confirmed=True)
    built = [
        lambda ya: em.confirm_email(em.sample_view(), 'tok-tok-tok-tok-tok-tok', your_ahavah=ya),
        lambda ya: em.reminder_email(view, 'tok-tok-tok-tok-tok-tok', your_ahavah=ya),
        lambda ya: em.change_email(view, 'tok-tok-tok-tok-tok-tok', {}, {}, your_ahavah=ya),
        lambda ya: em.cancelled_email(view, your_ahavah=ya),
        lambda ya: em.digest_email(em.sample_event(), [dict(name='Hannah', party_size=1)], 1,
                                   'tok-tok-tok-tok-tok-tok', your_ahavah=ya),
        lambda ya: em.manage_email('tok-tok-tok-tok-tok-tok', your_ahavah=ya),
        lambda ya: em.live_email(em.sample_event(), 'tok-tok-tok-tok-tok-tok', your_ahavah=ya),
        lambda ya: mm.mentor_invite_email('Rivka', 'she', mm.mentor_accept_url('tok'), your_ahavah=ya),
    ]
    for build in built:
        assert LINE not in build(False)[1]
        _, html = build(True)
        assert LINE in html
        # Under the footer's own reason, before Help.
        assert html.index('You are getting this' if 'You are getting this' in html else 'Ahavah &middot;') \
            < html.index(LINE) < html.index('>Help</a>')


# --- queueing -----------------------------------------------------------------

def _rsvp(client, slug):
    email = f'guest-{uuid4().hex[:8]}@ahavah-test.invalid'
    r = client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah', email=email, party_size=1))
    assert r.status_code == 201, r.get_data(as_text=True)
    [row] = _outbox('event_confirm', email=email)
    return row['payload']['html']


def test_a_guest_who_is_not_a_member_gets_it(client, published, line_on):
    assert LINE in _rsvp(client, published())


def test_not_while_the_switch_is_off(client, published, line_on, monkeypatch):
    monkeypatch.delenv(ENV)
    assert LINE not in _rsvp(client, published())


def test_not_while_the_light_sign_in_is_closed(client, published, line_on, monkeypatch):
    monkeypatch.delenv('AHAVAH_LIGHT_SIGN_IN_ENABLED')
    assert LINE not in _rsvp(client, published())


def _queue_change(slug):
    import json

    from service.events import mail
    with api_tx() as tx:
        tx.execute("UPDATE event SET changed_at = NOW(), change_before = %(b)s, change_after = %(a)s "
                   "WHERE slug = %(s)s", dict(s=slug, b=json.dumps(dict(date='a', time='b')),
                                               a=json.dumps(dict(date='c', time='b'))))
        eid = tx.execute('SELECT id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()['id']
        assert mail.queue_change(tx, eid) == 1


def test_a_lead_guest_hears_of_a_change_with_it(published, confirmed_guest, line_on):
    slug = published()
    g = confirmed_guest(slug)
    _queue_change(slug)
    [row] = _outbox('event_change', email=g['email'])
    assert LINE in row['payload']['html']


def test_a_guest_who_is_a_member_does_not(published, confirmed_guest, make_person, line_on):
    slug = published()
    address = f'mg-{uuid4().hex[:8]}@ahavah-test.invalid'
    p = make_person(name='MemberGuest', email=address)
    confirmed_guest(slug, email=address, person_id=p['id'])
    _queue_change(slug)
    [row] = _outbox('event_change', email=address)
    assert LINE not in row['payload']['html']


def test_an_organiser_gets_it_and_a_member_organiser_does_not(organiser, make_person, line_on):
    from service.events import mail
    from service.events.organisers import issue_link
    o = organiser()
    with api_tx() as tx:
        assert mail.queue_manage_link(tx, o['id'], issue_link(tx, o['id'])) is not None
    [row] = _outbox('event_manage', organiser_id=o['id'])
    assert LINE in row['payload']['html']

    m = organiser()
    p = make_person(name='HostMember')
    with api_tx() as tx:
        tx.execute('UPDATE organiser SET member_person_id = %(p)s WHERE id = %(i)s', dict(p=p['id'], i=m['id']))
        assert mail.queue_manage_link(tx, m['id'], issue_link(tx, m['id'])) is not None
    [row] = _outbox('event_manage', organiser_id=m['id'])
    assert LINE not in row['payload']['html']


def test_the_organiser_digest_carries_it(published, confirmed_guest, organiser, line_on):
    from service.events import mail
    o = organiser()
    slug = published(organiser_row=o)
    confirmed_guest(slug)
    with api_tx() as tx:
        eid = tx.execute('SELECT id FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone()['id']
        assert mail.queue_digest(tx, eid, date.today()) is not None
    [row] = _outbox('event_digest', organiser_id=o['id'])
    assert LINE in row['payload']['html']


def test_a_mentor_gets_it_and_a_member_mentor_does_not(client, make_person, sign_in, line_on, matchmaker_live):
    p = make_person(name='Rivka Levi', gender='Woman', email=f'rivka-{uuid4().hex[:8]}@ahavah-test.invalid')
    address = f'ruth-{uuid4().hex[:8]}@ahavah-test.invalid'
    assert client.post('/mentor/invite', headers=sign_in(p),
                       json=dict(email=address, relation='parent')).status_code == 201
    [row] = _outbox('mm_mentor_invite', email=address)
    assert LINE in row['payload']['html']

    q = make_person(name='Leah Levi', gender='Woman', email=f'leah-{uuid4().hex[:8]}@ahavah-test.invalid')
    naomi = f'naomi-{uuid4().hex[:8]}@ahavah-test.invalid'
    make_person(name='Naomi', gender='Woman', email=naomi)
    assert client.post('/mentor/invite', headers=sign_in(q),
                       json=dict(email=naomi, relation='parent')).status_code == 201
    [row] = _outbox('mm_mentor_invite', email=naomi)
    assert LINE not in row['payload']['html']


# --- at the send --------------------------------------------------------------

def _row(campaign, email, html):
    return dict(campaign=campaign, email=email, payload=dict(html=html))


def test_the_drain_takes_it_out_once_the_switch_is_off(monkeypatch, line_on):
    from emails import your_ahavah_line as yl
    from service.campaigns import outbox
    from service.events import mail
    _, html = mail.manage_email('tok-tok-tok-tok-tok-tok', your_ahavah=True)
    email = f'host-{uuid4().hex[:8]}@ahavah-test.invalid'
    with api_tx() as tx:
        assert yl.has_line(outbox._send_html(tx, _row('event_manage', email, html), html))
        monkeypatch.delenv(ENV)
        out = outbox._send_html(tx, _row('event_manage', email, html), html)
    assert LINE not in out and 'Manage your gatherings' in out


def test_the_drain_takes_it_out_once_the_address_has_joined(make_person, line_on):
    from service.campaigns import outbox
    from service.events import mail
    address = f'js-{uuid4().hex[:8]}@ahavah-test.invalid'
    make_person(name='JoinedSince', email=address)
    _, html = mail.cancelled_email(mail.sample_view(), your_ahavah=True)
    with api_tx() as tx:
        out = outbox._send_html(tx, _row('event_cancelled', address, html), html)
    assert LINE not in out and 'was cancelled' in out


def test_the_join_block_still_comes_out_beside_it(monkeypatch, line_on):
    """Both parts in one confirm email: each is read on its own."""
    from service.campaigns import outbox
    from service.events import mail
    _, html = mail.confirm_email(mail.sample_view(), 'tok-tok-tok-tok-tok-tok',
                                 join_url='https://ahavah.app/auth/sign-up?src=event:x', your_ahavah=True)
    monkeypatch.delenv('AHAVAH_EVENTS_JOIN_BLOCK_ENABLED', raising=False)
    email = f'guest-{uuid4().hex[:8]}@ahavah-test.invalid'
    with api_tx() as tx:
        out = outbox._send_html(tx, _row('event_confirm', email, html), html)
    assert LINE in out and 'Join Ahavah' not in out
