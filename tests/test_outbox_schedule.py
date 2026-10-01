"""A queued message can be held for a chosen slot (TEC-1613)."""
from datetime import datetime, timedelta, timezone

from database import api_tx
from service.campaigns import outbox
from service.cron.referralintro import queue_due


def _enqueue(pid, email, not_before=None, cid='sched-test'):
    with api_tx() as tx:
        return outbox.enqueue(
            tx, campaign='referral', campaign_id=cid, person_id=pid, email=email,
            subject='s', html='<p>h</p>', from_addr='support@ahavah.app',
            unsub_scope='notifications', not_before=not_before)


def test_a_held_row_is_not_reserved_until_its_slot(make_person):
    p = make_person(name='Held')
    later = datetime.now(timezone.utc) + timedelta(days=2)
    row_id = _enqueue(p['id'], f"held-{p['id']}@ahavah-test.invalid", not_before=later)
    assert row_id is not None
    with api_tx() as tx:
        reserved_ids = {r['id'] for r in outbox.reserve(tx, limit=1000)}
        tx.execute('ROLLBACK')
    assert row_id not in reserved_ids
    with api_tx('read committed') as tx:
        at = tx.execute("SELECT next_attempt_at FROM email_outbox WHERE id = %(i)s",
                        dict(i=row_id)).fetchone()['next_attempt_at']
    assert abs((at - later).total_seconds()) < 2


def test_without_a_slot_the_row_is_due_now(make_person):
    p = make_person(name='Now')
    row_id = _enqueue(p['id'], f"now-{p['id']}@ahavah-test.invalid")
    with api_tx('read committed') as tx:
        at = tx.execute("SELECT next_attempt_at FROM email_outbox WHERE id = %(i)s",
                        dict(i=row_id)).fetchone()['next_attempt_at']
    assert at <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_a_scheduled_referral_run_uses_its_own_id_and_cap(make_person):
    p = make_person(name='Sched')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      sign_up_time = NOW() - interval '10 days', referral_code = 'S1'
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"sched-{p['id']}@ahavah-test.invalid"))
    slot = datetime.now(timezone.utc) + timedelta(days=2)
    with api_tx() as tx:
        n = queue_due(tx, cap_days=1, not_before=slot, id_suffix='sched20261003T1200')
    assert n >= 1
    with api_tx('read committed') as tx:
        row = tx.execute(
            "SELECT campaign_id, payload, next_attempt_at FROM email_outbox WHERE person_id = %(p)s",
            dict(p=p['id'])).fetchone()
    assert row['campaign_id'] == f"referral-{p['id']}-sched20261003T1200"
    assert row['payload']['cap_days'] == 1
    assert abs((row['next_attempt_at'] - slot).total_seconds()) < 2
    # The cron's weekly tick the same day still queues its own row, and the
    # two never collide.
    with api_tx() as tx:
        assert queue_due(tx) >= 1
