"""GET /admin/growth/emails says what each number is (health review, 13 Oct
2026, finding 3).

`recipients` meant three things under one header: for e1, e2, e3 and e6 the
cohort before the frequency cap (which is neither who the last send reached
nor who a send would reach now: on 13 Oct the e2 row read 59 while a send
would have queued nobody), and for the system rows every row ever sent.
Each admin-run row now also carries:

- eligible_now: the cohort, unsubscribed and suppressed addresses already out
- would_reach_now: who a send pressed now would queue, after the cap
- last_run_reached: members the last run's mail was accepted for
- last_run_clicks: clicks on the links in that run's mail, bots excluded

`recipients` stays, equal to eligible_now, for the admin build that reads it.
The admin-session fixture is copied from tests/test_growth_routes.py: test
files here do not import from each other."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone

import pytest

from database import api_tx
import emails.send_community_weekly as e2
import emails.send_notifications_nudge as e6
from service.campaigns import log_send, make_campaign_link
from service.campaigns.weekid import week_campaign_id
from service.config import WEB_BASE_URL

RUN_FIELDS = ('eligible_now', 'would_reach_now', 'last_run_reached', 'last_run_clicks')


def _bearer(person_id: int, email: str) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def admin(make_person):
    p = make_person(name='IndexAdmin')
    with api_tx() as tx:
        email = tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s RETURNING email",
                           dict(i=p['id'])).fetchone()['email']
    return _bearer(p['id'], email)


def _sendable(person_id: int, label: str) -> str:
    email = f'{label}-{person_id}@ahavah-test.invalid'
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(e=email, i=person_id))
    return email


def _log(person_id: int, campaign: str, campaign_id: str, ago: str) -> None:
    """A send-log row dated `ago` from now: an interval such as '2 days', or
    '-1 hour' for an hour ahead, which makes the run the latest on file."""
    with api_tx() as tx:
        log_send(tx, person_id, campaign, campaign_id, 'mid')
        tx.execute(
            """UPDATE email_send_log SET sent_at = NOW() - %(a)s::interval
                WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
            dict(a=ago, p=person_id, c=campaign, cid=campaign_id))


def _index(client, admin) -> dict:
    r = client.get('/admin/growth/emails', headers=admin)
    assert r.status_code == 200
    return {c['campaign']: c for c in r.get_json()['campaigns']}


def test_every_row_names_its_figures(client, admin):
    rows = _index(client, admin)
    for key in ('e1', 'e2', 'e3', 'e6'):
        row = rows[key]
        assert isinstance(row['eligible_now'], int) and isinstance(row['would_reach_now'], int)
        assert row['recipients'] == row['eligible_now']
        assert 0 <= row['would_reach_now'] <= row['eligible_now']
        assert isinstance(row['people_reached'], int)
    # The platform sends these one member at a time, so there is no cohort
    # and no run: the run figures are null, and people_reached counts
    # distinct people where `recipients` counts every row.
    for key in ('e4', 'e5', 'welcome', 'referral'):
        row = rows[key]
        assert all(row[f] is None for f in RUN_FIELDS)
        assert isinstance(row['people_reached'], int)
        assert row['people_reached'] <= row['recipients']


def test_would_reach_now_leaves_out_who_the_cap_holds(client, admin, make_person, monkeypatch):
    capped = make_person(name='Capped')
    free = make_person(name='Free')
    this_week = make_person(name='ThisWeek')
    rows = []
    for p in (capped, free, this_week):
        rows.append(dict(e2.preview_row(_sendable(p['id'], 'reach')), person_id=p['id'], name='Reach'))
    # Inside e2's 6 day cap.
    _log(capped['id'], 'e6', f'e6-cap-{uuid.uuid4().hex[:6]}', '2 days')
    # Outside it.
    _log(free['id'], 'e6', f'e6-cap-{uuid.uuid4().hex[:6]}', '6 days 12 hours')
    # Outside the cap too, but already has this week's e2: the week's id is
    # the one a send pressed now would use, and the runner skips a repeat.
    _log(this_week['id'], 'e2', week_campaign_id(datetime.now(timezone.utc), 'e2'), '6 days 12 hours')
    monkeypatch.setattr(e2, 'recipients', lambda: rows)
    monkeypatch.setattr(e6, 'recipients', lambda: rows)

    out = _index(client, admin)

    assert out['e2']['eligible_now'] == 3 and out['e2']['recipients'] == 3
    assert out['e2']['would_reach_now'] == 1
    # e6 has the default 7 day cap, so 6 and a half days ago still holds,
    # whichever campaign it was.
    assert out['e6']['eligible_now'] == 3
    assert out['e6']['would_reach_now'] == 0


def test_would_reach_now_leaves_out_who_unsubscribed(client, admin, make_person):
    from service.unsubscribe import stamp_unsubscribed
    p = make_person(name='Leaving')
    email = _sendable(p['id'], 'unsub-reach')
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() WHERE id = %(i)s", dict(i=p['id']))
    before = _index(client, admin)['e6']
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'notifications', email)
    after = _index(client, admin)['e6']
    assert after['eligible_now'] == before['eligible_now'] - 1
    assert after['would_reach_now'] == before['would_reach_now'] - 1


@pytest.fixture
def run_links():
    keys = []
    yield keys
    with api_tx() as tx:
        tx.execute("DELETE FROM campaign_link WHERE key = ANY(%(k)s)", dict(k=keys))


def _queue(person_id: int, campaign: str, campaign_id: str, email: str, html: str) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload,
                                          unsub_scope, state, sent_at)
               VALUES (%(c)s, %(cid)s, %(p)s, %(e)s, %(payload)s, 'notifications', 'accepted', NOW())""",
            dict(c=campaign, cid=campaign_id, p=person_id, e=email,
                 payload=json.dumps(dict(subject='S', html=html, from_addr='support@ahavah.app'))))


def _link(person_id: int, campaign: str, keys: list) -> str:
    with api_tx() as tx:
        url = make_campaign_link(tx, campaign, f'{WEB_BASE_URL}/settings/notifications', person_id)
    keys.append(url.rsplit('/', 1)[1])
    return url


def _click(url: str, ua_class: str) -> None:
    with api_tx() as tx:
        tx.execute("INSERT INTO campaign_click (link_key, ua_class) VALUES (%(k)s, %(u)s)",
                   dict(k=url.rsplit('/', 1)[1], u=ua_class))


def test_the_last_run_reports_who_it_reached_and_their_clicks(client, admin, make_person, run_links):
    a = make_person(name='RunA')
    b = make_person(name='RunB')
    cid = f'e6-run-{uuid.uuid4().hex[:8]}'
    links = {}
    for p in (a, b):
        email = _sendable(p['id'], 'run')
        links[p['id']] = _link(p['id'], 'e6', run_links)
        _queue(p['id'], 'e6', cid, email, f'<a href="{links[p["id"]]}">Turn them on</a>')
        _log(p['id'], 'e6', cid, '-1 hour')
    _click(links[a['id']], 'mobile')
    _click(links[a['id']], 'desktop')
    _click(links[b['id']], 'bot')
    # A link of the same campaign that was not in this run's mail.
    elsewhere = _link(a['id'], 'e6', run_links)
    _click(elsewhere, 'mobile')

    row = _index(client, admin)['e6']

    assert row['last_campaign_id'] == cid
    assert row['last_run_reached'] == 2
    assert row['last_run_clicks'] == 2


def test_a_run_with_no_tracked_links_reports_no_clicks_rather_than_zero(client, admin, make_person):
    """e1's mail carries a signed confirm link, not a /s/ link, so its
    clicks are not counted anywhere yet (finding 90). Zero would claim
    nobody clicked."""
    p = make_person(name='Untracked')
    cid = f'e1-run-{uuid.uuid4().hex[:8]}'
    email = _sendable(p['id'], 'untracked')
    _queue(p['id'], 'e1', cid, email, '<a href="https://ahavah.app/spotlight/confirm/t">Yes</a>')
    _log(p['id'], 'e1', cid, '-1 hour')

    row = _index(client, admin)['e1']

    assert row['last_campaign_id'] == cid
    assert row['last_run_reached'] == 1
    assert row['last_run_clicks'] is None
