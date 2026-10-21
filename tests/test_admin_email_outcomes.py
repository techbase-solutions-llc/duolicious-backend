"""What each email achieved (TEC-1897; frames G.1, G.2 and G.4): came back
any time and within 7 days, push turned on, and each run's history."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx
from service.admin import record_system_audit
from service.campaigns.runner import SEND_AUDIT_ACTION
from service.growth import email_outcomes


def _send(person, campaign: str, cid: str, hours_ago: float = 1) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, %(c)s, %(cid)s, NOW() - make_interval(secs => %(s)s))""",
                   dict(p=person['id'], c=campaign, cid=cid, s=hours_ago * 3600))


def _online(person, *, days_ago: int = 0, recorded: bool = True) -> None:
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - make_interval(days => %(d)s) WHERE id = %(i)s",
                   dict(d=days_ago, i=person['id']))
        if recorded:
            tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                          VALUES (%(i)s, (NOW() AT TIME ZONE 'America/Barbados')::date
                                         - %(d)s, NOW() - make_interval(days => %(d)s),
                                         NOW() - make_interval(days => %(d)s))
                          ON CONFLICT (person_id, day) DO UPDATE SET last_at = EXCLUDED.last_at""",
                       dict(i=person['id'], d=days_ago))


def _recording_since_a_month_ago(make_person) -> None:
    """The per-day record must predate the run for a 7 day figure."""
    keeper = make_person(name='RecKeeper')
    with api_tx() as tx:
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(i)s, CURRENT_DATE - 30, NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days')""",
                   dict(i=keeper['id']))


def test_came_back_and_push_turned_on_for_one_run(make_person):
    _recording_since_a_month_ago(make_person)
    back, away, pushed = (make_person(name=n) for n in ('OutBack', 'OutAway', 'OutPush'))
    cid = f'test-{uuid4().hex[:8]}'
    for p in (back, away, pushed):
        _send(p, 'e6', cid, hours_ago=2)
    _online(back)
    _online(away, days_ago=1, recorded=False)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, %(e)s, 'k', 'a')""", dict(i=pushed['id'], e=f'https://push.test/{uuid4()}'))
        out = email_outcomes.run_outcomes(tx, 'e6', cid)
    # pushed's last_online_time is make_person's default NOW(), after the send.
    assert out == dict(came_back=2, came_back_7d=1, push_turned_on=1)


def test_seven_days_is_not_measured_before_the_record_began(make_person):
    p = make_person(name='OutOld')
    cid = f'test-{uuid4().hex[:8]}'
    _send(p, 'e2', cid, hours_ago=24 * 400)
    with api_tx() as tx:
        out = email_outcomes.run_outcomes(tx, 'e2', cid)
    assert out['came_back'] == 1 and out['came_back_7d'] is None and out['push_turned_on'] is None


def test_started_by():
    assert email_outcomes.started_by('cron') == 'schedule'
    assert email_outcomes.started_by('cli') == 'command_line'
    assert email_outcomes.started_by('owner@example.com') == 'send_button'
    assert email_outcomes.started_by(None) is None


def test_run_history_and_the_last_30_days(client, admin_bearer, make_person):
    a, b = make_person(name='HistA'), make_person(name='HistB')
    cid = f'test-{uuid4().hex[:8]}'
    _send(a, 'e2', cid, hours_ago=0.5)
    _send(b, 'e2', cid, hours_ago=0.5)
    with api_tx() as tx:
        record_system_audit(tx, 'cron', SEND_AUDIT_ACTION,
                            dict(campaign='e2', campaign_id=cid, dry_run=False, queued=2))
    r = client.get('/admin/growth/emails/e2/runs', headers=admin_bearer)
    assert r.status_code == 200
    body = r.get_json()
    run = next(x for x in body['runs'] if x['campaign_id'] == cid)
    assert run['started_by'] == 'schedule' and run['reached'] == 2
    assert run['came_back'] == 2 and run['clicks'] is None
    assert run['sent_at'].endswith('+00:00')
    assert body['last_30_days']['sends'] >= 2 and body['last_30_days']['people'] >= 2


def test_runs_are_for_admin_run_emails_only(client, admin_bearer):
    assert client.get('/admin/growth/emails/welcome/runs', headers=admin_bearer).status_code == 404
    assert client.get('/admin/growth/emails/e9/runs', headers=admin_bearer).status_code == 404


def test_the_emails_index_carries_the_outcomes(client, admin_bearer, make_person):
    p = make_person(name='IdxBack')
    _send(p, 'welcome', f'test-{uuid4().hex[:8]}', hours_ago=1)
    body = client.get('/admin/growth/emails', headers=admin_bearer).get_json()['campaigns']
    rows = {c['campaign']: c for c in body}
    for key in ('e1', 'e2', 'e3', 'e6'):
        assert {'last_run_came_back', 'last_run_came_back_7d', 'last_run_push_turned_on'} <= set(rows[key])
    assert rows['e2']['last_run_push_turned_on'] is None
    assert rows['welcome']['came_back'] >= 1
