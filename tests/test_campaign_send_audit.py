"""Every campaign send leaves an audit row, wherever it was started (health
review, 13 Oct 2026, finding 20).

Only the admin's Send button wrote one. The e3 and e6 runs of 1 Oct were
sent from the command line, the referral run of 4 Oct from
scripts/schedule_referral_intro.py and the weekly e2 by its cron, and none
of them is in admin_audit_log. A send with no admin behind it is recorded
under a system actor: actor_email 'cli' or 'cron', the nil uuid."""
from __future__ import annotations

import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
import emails.send_community_weekly as e2
import emails.send_notifications_nudge as e6
import emails.send_reinvite as e3
import emails.send_spotlight_announcement as e1

NIL_UUID = '00000000-0000-0000-0000-000000000000'


def _audit_rows(**match):
    where = ' AND '.join(f"metadata->>'{k}' = %({k})s" for k in match)
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            f"""SELECT actor_email, actor_uuid::text AS actor_uuid, metadata
                  FROM admin_audit_log
                 WHERE action = 'growth.email.send' AND {where}
                 ORDER BY created_at""", match).fetchall()]


@pytest.fixture
def cid():
    value = f'audit-{uuid.uuid4().hex[:10]}'
    yield value
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE metadata->>'campaign_id' = %(c)s", dict(c=value))


def _sendable(person_id: int, label: str) -> str:
    email = f'{label}-{person_id}@ahavah-test.invalid'
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(e=email, i=person_id))
    return email


# ---------------------------------------------------------------------------
# The command line: python -m emails.send_<campaign> --send
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('mod,key', [(e1, 'e1'), (e2, 'e2'), (e3, 'e3'), (e6, 'e6')])
def test_a_send_from_the_command_line_is_audited(make_person, monkeypatch, cid, mod, key):
    # make_person's @example.com address is suppressed, so the run reaches a
    # real recipient and queues nothing: an audit row is about the run, not
    # about how many it reached.
    p = make_person(name='CliTarget')
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=p['id'])).fetchone()['email']
    monkeypatch.setattr(mod, 'recipients', lambda *a, **k: [dict(person_id=p['id'], email=email, name='CliTarget')])
    monkeypatch.setattr('sys.argv', ['send', '--send', '--campaign-id', cid])

    mod.main()

    rows = _audit_rows(campaign_id=cid)
    assert len(rows) == 1
    assert rows[0]['actor_email'] == 'cli' and rows[0]['actor_uuid'] == NIL_UUID
    assert rows[0]['metadata']['campaign'] == key
    assert rows[0]['metadata']['dry_run'] is False
    assert rows[0]['metadata']['skipped_suppressed'] == 1


def test_a_dry_run_from_the_command_line_is_not_audited(make_person, monkeypatch, cid):
    p = make_person(name='CliDry')
    monkeypatch.setattr(e6, 'recipients', lambda: [dict(person_id=p['id'], email='x@example.com', name='CliDry')])
    monkeypatch.setattr('sys.argv', ['send', '--campaign-id', cid])
    e6.main()
    assert _audit_rows(campaign_id=cid) == []


# ---------------------------------------------------------------------------
# The weekly cron (e2)
# ---------------------------------------------------------------------------

def test_a_weekly_cron_send_is_audited_once(make_person, monkeypatch, cid):
    import service.cron.communityweekly as cron
    p = make_person(name='CronWeekly')
    email = _sendable(p['id'], 'cron-weekly')
    monkeypatch.setattr(cron, 'is_send_window', lambda now: True)
    monkeypatch.setattr(cron, 'week_campaign_id', lambda now, campaign: cid)
    monkeypatch.setattr(cron, 'recipients', lambda: [dict(person_id=p['id'], email=email, name='CronWeekly')])
    monkeypatch.setattr(cron, 'build_for', lambda row: ('This week on Ahavah', '<p>hi</p>'))

    cron._send_once()
    # Every later tick on a Monday queues nothing, and says nothing.
    cron._send_once()

    rows = _audit_rows(campaign_id=cid)
    assert len(rows) == 1
    assert rows[0]['actor_email'] == 'cron' and rows[0]['actor_uuid'] == NIL_UUID
    assert rows[0]['metadata']['campaign'] == 'e2' and rows[0]['metadata']['queued'] == 1


# ---------------------------------------------------------------------------
# The referral intro: its cron, and the one-off scheduler
# ---------------------------------------------------------------------------

def _due_member(make_person, name):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      sign_up_time = NOW() - interval '10 days', referral_code = %(c)s
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", c=f"AUD{p['id']}"))
    return p


def _referral_rows(suffix):
    return _audit_rows(campaign='referral', id_suffix=suffix)


def _clear_referral_rows(suffix):
    with api_tx() as tx:
        tx.execute("""DELETE FROM admin_audit_log
                       WHERE metadata->>'campaign' = 'referral' AND metadata->>'id_suffix' = %(s)s""",
                   dict(s=suffix))


def test_a_referral_cron_tick_that_queues_is_audited(make_person):
    from service.cron.referralintro import _tick
    _due_member(make_person, 'AuditDue')
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    suffix = f'{y}w{w:02d}'
    _clear_referral_rows(suffix)
    try:
        _tick()
        rows = _referral_rows(suffix)
        assert len(rows) == 1
        assert rows[0]['actor_email'] == 'cron' and rows[0]['actor_uuid'] == NIL_UUID
        assert rows[0]['metadata']['queued'] >= 1
        # The next tick finds the member already queued and writes nothing.
        _tick()
        assert len(_referral_rows(suffix)) == 1
    finally:
        _clear_referral_rows(suffix)


def test_a_scheduled_referral_run_is_audited(make_person, monkeypatch):
    import importlib
    script = importlib.import_module('scripts.schedule_referral_intro')
    _due_member(make_person, 'AuditSched')
    at = (datetime.now(timezone.utc) + timedelta(days=400)).replace(microsecond=0)
    suffix = 'sched' + at.strftime('%Y%m%dT%H%M')
    monkeypatch.setattr('sys.argv', ['schedule', '--at', at.isoformat(), '--cap-days', '1'])
    try:
        script.main()
        rows = _referral_rows(suffix)
        assert len(rows) == 1
        assert rows[0]['actor_email'] == 'cli'
        assert rows[0]['metadata']['queued'] >= 1
        assert rows[0]['metadata']['cap_days'] == 1
    finally:
        _clear_referral_rows(suffix)


# ---------------------------------------------------------------------------
# Guard: a new send path cannot ship without an audit row.
# ---------------------------------------------------------------------------

def test_every_caller_of_the_campaign_runner_writes_an_audit_row():
    root = pathlib.Path(__file__).resolve().parent.parent
    callers = []
    for path in [*root.glob('emails/*.py'), *root.glob('scripts/*.py'), *root.glob('service/**/*.py')]:
        if path.name == 'runner.py':
            continue
        text = path.read_text(encoding='utf-8')
        # A caller imports it; a comment that names it does not count.
        if re.search(r'from service\.campaigns\.runner import[^\n]*\brun_campaign\b', text):
            callers.append(path)
            assert re.search(r'\b(audit_send|record_audit)\(', text), \
                f'{path.relative_to(root)} sends a campaign and writes no audit row'
    # The four campaign scripts, the weekly cron and the admin route.
    assert len(callers) >= 6
