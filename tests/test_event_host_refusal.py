"""Refusing a request to host, with the reason (TEC-1845; ahavah-web Claude
Design "Ahavah In-app Entry Round 2.html", 8.7; copy pass of 23 Oct 2026,
claim 3 and the owner's answer: "the admin types a short reason when
refusing and the person gets one email with it").

Migration 0088 keeps the reason and when it was refused on the organiser.
The email is behind its own switch, events_host_refusal_email (which needs
events_live), and /events/status reports it, so the web shows 8.7's line
"We have emailed you the reason" only while it is on."""
from pathlib import Path

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')

ENV = 'AHAVAH_EVENTS_HOST_REFUSAL_EMAIL_ENABLED'
MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0088_organiser_refusal.sql'
REASON = 'We only approve hosts who run gatherings in person for now. <b>Thank you</b> for asking.'


@pytest.fixture
def refusal_on(monkeypatch):
    monkeypatch.setenv(ENV, '1')


def _organiser(oid):
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM organiser WHERE id = %(i)s', dict(i=oid)).fetchone())


def _emails(oid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'event_host_refused' AND organiser_id = %(o)s",
            dict(o=oid)).fetchall()]


def _decline(client, admin_headers, oid, **body):
    return client.post(f'/admin/events/organisers/{oid}/decline', headers=admin_headers, json=body or None)


# --- the migration and the switch ---------------------------------------------

def test_the_migration_runs_twice_and_bounds_its_lock_wait():
    sql = MIGRATION.read_text(encoding='utf-8')
    assert "SET lock_timeout = '5s';" in sql and 'RESET lock_timeout;' in sql
    with api_tx() as tx:
        tx.execute(sql)
        tx.execute(sql)


def test_the_migration_number_is_this_rounds():
    """0088 to 0091 are this round's; another round takes 0092 on."""
    assert 88 <= int(MIGRATION.name[:4]) <= 91


def test_the_columns():
    with api_tx('read committed') as tx:
        cols = {r['column_name']: r for r in tx.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'organiser'"
        ).fetchall()}
    assert cols['refusal_reason']['is_nullable'] == 'YES' and cols['refused_at']['is_nullable'] == 'YES'


def test_the_switch_and_the_compose_file():
    import pathlib

    from service.campaigns.switches import SWITCHES
    from service.events import CAMPAIGN_SWITCHES
    assert SWITCHES['events_host_refusal_email'] == ENV
    assert CAMPAIGN_SWITCHES['event_host_refused'] == 'events_host_refusal_email'
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{ENV}: ${{{ENV}:-0}}') == 2


def test_the_status_reports_it_and_it_needs_events_live(client, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert client.get('/events/status').get_json()['refusal_email'] is False
    monkeypatch.setenv(ENV, '1')
    assert client.get('/events/status').get_json()['refusal_email'] is True
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    assert client.get('/events/status').get_json()['refusal_email'] is False


# --- declining ------------------------------------------------------------------

def test_declining_keeps_the_reason_and_emails_it(client, admin_headers, organiser, refusal_on):
    o = organiser(approved=False)
    r = _decline(client, admin_headers, o['id'], reason=f'  {REASON}  ')
    assert r.status_code == 200, r.get_data(as_text=True)
    row = _organiser(o['id'])
    assert row['refusal_reason'] == REASON and row['refused_at'] is not None and row['revoked_at'] is not None
    [mail] = _emails(o['id'])
    html = mail['payload']['html']
    assert mail['email'] == o['email'] and mail['payload']['subject'] == 'Your request to host on Ahavah'
    assert 'We could not approve your request to host on Ahavah.' in html
    assert 'We only approve hosts who run gatherings in person for now. &lt;b&gt;Thank you&lt;/b&gt;' in html
    assert '<b>Thank you</b>' not in html
    assert 'Reply to this email if you would like to talk it through.' in html
    assert 'You are getting this because you asked to host gatherings on Ahavah.' in html
    assert 'title-note.png' in html
    # The admin's reason is audited as given, not only that there was one.
    with api_tx('read committed') as tx:
        audit = tx.execute("""SELECT metadata FROM admin_audit_log WHERE action = 'events.organiser.decline'
                                 AND metadata->>'organiser_id' = %(o)s""", dict(o=str(o['id']))).fetchone()
    assert audit['metadata']['reason'] == REASON


def test_no_email_while_the_switch_is_off_but_the_reason_is_kept(client, admin_headers, organiser, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    o = organiser(approved=False)
    assert _decline(client, admin_headers, o['id'], reason='Not this time.').status_code == 200
    assert _organiser(o['id'])['refusal_reason'] == 'Not this time.' and _emails(o['id']) == []


def test_without_a_reason_it_still_declines_and_sends_nothing(client, admin_headers, organiser, refusal_on):
    """An admin page from before this change posts no body: the decline
    still works, and there is no reason to send."""
    o = organiser(approved=False)
    assert client.post(f"/admin/events/organisers/{o['id']}/decline", headers=admin_headers).status_code == 200
    row = _organiser(o['id'])
    assert row['revoked_at'] is not None and row['refusal_reason'] is None and _emails(o['id']) == []
    p = organiser(approved=False)
    assert _decline(client, admin_headers, p['id'], reason='   ').status_code == 200
    assert _organiser(p['id'])['refusal_reason'] is None and _emails(p['id']) == []


def test_a_reason_over_500_characters_is_refused(client, admin_headers, organiser, refusal_on):
    o = organiser(approved=False)
    assert _decline(client, admin_headers, o['id'], reason='x' * 501).status_code == 400
    assert _organiser(o['id'])['revoked_at'] is None and _emails(o['id']) == []


def test_an_organiser_already_revoked_is_not_emailed(client, admin_headers, organiser, refusal_on):
    o = organiser(approved=False)
    client.post(f"/admin/events/organisers/{o['id']}/revoke", headers=admin_headers)
    assert _decline(client, admin_headers, o['id'], reason='Not this time.').status_code == 200
    assert _emails(o['id']) == []


def test_the_drain_holds_it_once_the_switch_is_off(client, admin_headers, organiser, refusal_on, monkeypatch):
    from service.campaigns import outbox
    o = organiser(approved=False)
    _decline(client, admin_headers, o['id'], reason='Not this time.')
    [mail] = _emails(o['id'])
    monkeypatch.delenv(ENV)
    with api_tx() as tx:
        assert outbox._refusal(tx, mail) == 'switched_off'
