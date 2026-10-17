"""Match and message reminders (finding 61): held behind their own switches,
push first where the member has push for that event, otherwise email
through the outbox, once per stage, stopping once anyone writes."""
from datetime import datetime, timezone
import secrets

import pytest

from database import api_tx
from emails import reminders as rm
from service.config import WEB_BASE_URL

TUESDAY = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 10, 17, 13, tzinfo=timezone.utc)


def _person(make_person, name, gender='Woman', offline_days=2):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      last_online_time = NOW() - make_interval(days => %(d)s)
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", d=offline_days))
    return p


def _match(a, b, days_ago):
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        return str(tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
               VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s)) RETURNING match_id""",
            dict(a=lo, b=hi, d=days_ago)).fetchone()['match_id'])


def _days_ago_us(days_ago, now_sql='NOW()'):
    """The inbox timestamp (microseconds since the epoch) of a message sent
    `days_ago` whole days, and a minute, before `now_sql`. Floored, not
    cast: `::bigint` rounds to the nearest second, which half the time
    dated the message just after the day mark."""
    return (f"(floor(EXTRACT(EPOCH FROM {now_sql} - make_interval(days => {int(days_ago)}, mins => 1)))"
            f"::bigint * 1000000)")


def test_the_helper_never_dates_a_message_after_its_day_mark():
    """A message dated even a fraction of a second after the 3-day mark is
    2 days old to the reminder's floor(), and was the 1-in-4 flake of
    test_an_unread_message_three_days_old_is_reminded_once."""
    now = "'2026-10-13 13:00:00.9+00'::timestamptz"
    with api_tx('read committed') as tx:
        row = tx.execute(f"""SELECT {_days_ago_us(3, now)} AS ts,
                                    EXTRACT(EPOCH FROM {now} - interval '3 days') * 1000000 AS mark""").fetchone()
    assert row['ts'] <= row['mark']


def _unread(reader, sender, days_ago, unread=1):
    ts = _days_ago_us(days_ago)
    with api_tx() as tx:
        tx.execute(
            f"""INSERT INTO inbox (luser, remote_bare_jid, msg_id, box, content, timestamp, unread_count)
                VALUES (%(l)s, %(r)s, %(m)s, 'chats', ''::bytea, {ts}, %(n)s)""",
            dict(l=reader['uuid'], r=f"{sender['uuid']}@duolicious.app", m=secrets.token_hex(8), n=unread))


def _cleanup_inbox(*people):
    with api_tx() as tx:
        for p in people:
            tx.execute("DELETE FROM inbox WHERE luser = %(u)s", dict(u=p['uuid']))


def _outbox(pid, campaign):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, unsub_scope, exempt, payload->>'html' AS html,
                      payload->>'subject' AS subject
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = %(c)s""",
            dict(p=pid, c=campaign)).fetchall()]


def _pushes(pid, campaign):
    with api_tx('read committed') as tx:
        return [r['campaign_id'] for r in tx.execute(
            "SELECT campaign_id FROM push_send_log WHERE person_id = %(p)s AND campaign = %(c)s",
            dict(p=pid, c=campaign)).fetchall()]


@pytest.fixture
def pushed(monkeypatch):
    """Capture pushes instead of sending them; push counts as configured."""
    sent = []
    monkeypatch.setattr(rm, '_push', lambda person_id, title, body, url, kind: sent.append(
        dict(person_id=person_id, title=title, body=body, url=url, kind=kind)))
    monkeypatch.setattr(rm, 'PUSH_READY', lambda: True)
    return sent


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_MATCH_REMINDER_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MESSAGE_REMINDER_ENABLED', '1')


def _run(now=TUESDAY):
    from service.campaigns import held
    with api_tx() as tx:
        n = rm.queue_match_reminders(tx, now) + rm.queue_message_reminders(tx, now)
    held.run_after_commit()
    return n


def test_off_by_default(make_person, monkeypatch, pushed):
    monkeypatch.delenv('AHAVAH_MATCH_REMINDER_ENABLED', raising=False)
    monkeypatch.delenv('AHAVAH_MESSAGE_REMINDER_ENABLED', raising=False)
    a, b = _person(make_person, 'OffA'), _person(make_person, 'OffB', 'Man')
    _match(a, b, 4)
    _unread(a, b, 4)
    try:
        assert _run() == 0
        assert _outbox(a['id'], 'match_reminder') == [] and pushed == []
    finally:
        _cleanup_inbox(a)


def test_a_silent_match_reminds_both_sides_by_email(make_person, on, pushed):
    a, b = _person(make_person, 'SilentA'), _person(make_person, 'SilentB', 'Man')
    mid = _match(a, b, 4)
    _run()
    for p in (a, b):
        rows = _outbox(p['id'], 'match_reminder')
        assert len(rows) == 1
        r = rows[0]
        assert r['campaign_id'] == f'match_reminder-{mid}-d3'
        assert r['unsub_scope'] == 'notifications' and r['exempt'] is True
        assert '4 days ago' in r['html'] and 'neither of you has written yet' in r['html']
        assert 'SilentA' not in r['html'] and 'SilentB' not in r['html'], 'the reminder named the match'
        assert f'{WEB_BASE_URL}/s/' in r['html']
    _run()
    assert len(_outbox(a['id'], 'match_reminder')) == 1, 'a second tick reminded again'


def test_the_second_stage_follows_at_10_days(make_person, on, pushed):
    a, b = _person(make_person, 'LaterA'), _person(make_person, 'LaterB', 'Man')
    mid = _match(a, b, 11)
    _run()
    assert [r['campaign_id'] for r in _outbox(a['id'], 'match_reminder')] == [f'match_reminder-{mid}-d10']


def test_no_reminder_once_either_side_has_written_or_too_soon(make_person, on, pushed):
    a, b = _person(make_person, 'WroteA'), _person(make_person, 'WroteB', 'Man')
    _match(a, b, 4)
    with api_tx() as tx:
        tx.execute("INSERT INTO messaged (subject_person_id, object_person_id) VALUES (%(a)s, %(b)s)",
                   dict(a=b['id'], b=a['id']))
    c, d = _person(make_person, 'SoonC'), _person(make_person, 'SoonD', 'Man')
    _match(c, d, 1)
    _run()
    for p in (a, b, c, d):
        assert _outbox(p['id'], 'match_reminder') == []


def test_a_member_with_push_for_matches_gets_a_push_not_an_email(make_person, on, pushed):
    a, b = _person(make_person, 'PushA'), _person(make_person, 'PushB', 'Man')
    mid = _match(a, b, 4)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(p)s, %(e)s, 'k', 'a')""", dict(p=a['id'], e=f'https://push.test/{a["id"]}'))
    _run()
    _run()
    assert [x for x in pushed if x['person_id'] == a['id']] == [dict(
        person_id=a['id'], title='Say hello to your match',
        body='Neither of you has written yet. A short hello is enough.', url='/matches', kind='match')]
    assert _pushes(a['id'], 'match_reminder') == [f'match_reminder-{mid}-d3']
    assert _outbox(a['id'], 'match_reminder') == []
    assert len(_outbox(b['id'], 'match_reminder')) == 1


def test_a_push_waits_for_the_transaction_to_commit(make_person, on, pushed):
    """send_to_user_safe re-reads preferences in its own transaction, which
    must never open inside the job's (api_tx is never nested)."""
    from service.campaigns import held
    a, b = _person(make_person, 'WaitA'), _person(make_person, 'WaitB', 'Man')
    _match(a, b, 4)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(p)s, %(e)s, 'k', 'a')""", dict(p=a['id'], e=f'https://push.test/{a["id"]}'))
    with api_tx() as tx:
        rm.queue_match_reminders(tx, TUESDAY)
        assert [x for x in pushed if x['person_id'] == a['id']] == []
    held.run_after_commit()
    assert len([x for x in pushed if x['person_id'] == a['id']]) == 1


def test_a_member_who_turned_match_emails_off_gets_nothing_by_email(make_person, on, pushed):
    a, b = _person(make_person, 'NoMailA'), _person(make_person, 'NoMailB', 'Man')
    _match(a, b, 4)
    with api_tx() as tx:
        tx.execute("""INSERT INTO notification_preference (person_id, email_matches)
                      VALUES (%(p)s, FALSE)
                      ON CONFLICT (person_id) DO UPDATE SET email_matches = FALSE""", dict(p=a['id']))
    _run()
    assert _outbox(a['id'], 'match_reminder') == []


def test_an_unread_message_three_days_old_is_reminded_once(make_person, on, pushed):
    reader, sender = _person(make_person, 'Reader', offline_days=5), _person(make_person, 'Sender', 'Man')
    _unread(reader, sender, 3)
    try:
        _run()
        _run()
        rows = _outbox(reader['id'], 'message_reminder')
        assert len(rows) == 1
        r = rows[0]
        assert r['campaign_id'].startswith('message_reminder-') and r['campaign_id'].endswith('-d3')
        assert r['subject'] == 'Someone is waiting for your reply'
        assert 'Sender' not in r['html']
        assert r['unsub_scope'] == 'notifications'
    finally:
        _cleanup_inbox(reader)


def test_no_message_reminder_once_read_or_when_online_since(make_person, on, pushed):
    read = _person(make_person, 'AlreadyRead', offline_days=5)
    online = _person(make_person, 'OnlineSince', offline_days=0)
    sender = _person(make_person, 'Sender2', 'Man')
    _unread(read, sender, 4, unread=0)
    _unread(online, sender, 4)
    try:
        _run()
        assert _outbox(read['id'], 'message_reminder') == []
        assert _outbox(online['id'], 'message_reminder') == []
    finally:
        _cleanup_inbox(read, online)


def test_several_unread_conversations_make_one_reminder(make_person, on, pushed):
    reader = _person(make_person, 'ManyReader', offline_days=6)
    s1, s2 = _person(make_person, 'S1', 'Man'), _person(make_person, 'S2', 'Man')
    _unread(reader, s1, 4)
    _unread(reader, s2, 5)
    try:
        _run()
        rows = _outbox(reader['id'], 'message_reminder')
        assert len(rows) == 1 and rows[0]['subject'] == '2 people are waiting for your reply'
    finally:
        _cleanup_inbox(reader)


def test_no_reminders_on_the_sabbath(make_person, on, pushed):
    a, b = _person(make_person, 'SabA'), _person(make_person, 'SabB', 'Man')
    _match(a, b, 4)
    assert _run(SATURDAY) == 0


def test_previews_write_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    s1, h1 = rm.preview_match('owner@ahavah-test.invalid')
    s2, h2 = rm.preview_message('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert s1 == 'Your match is waiting for a hello' and 'title-match.png' in h1
    assert s2 == 'Someone is waiting for your reply' and 'title-message.png' in h2
    assert rm.PUSH_PROOFS == [
        dict(title='Say hello to your match', body='Neither of you has written yet. A short hello is enough.',
             url='/matches', kind='match'),
        dict(title='A message is waiting for you', body='Someone is waiting for your reply on Ahavah.',
             url='/inbox', kind='message'),
    ]


def _make_staff(person):
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(p)s", dict(p=person['id']))


def test_never_to_staff(make_person, on, pushed):
    staff, member = _person(make_person, 'StaffMatch'), _person(make_person, 'MemberMatch', 'Man')
    _make_staff(staff)
    _match(staff, member, 4)
    reader, sender = _person(make_person, 'StaffReader', offline_days=5), _person(make_person, 'StaffSender', 'Man')
    _make_staff(reader)
    _unread(reader, sender, 4)
    try:
        _run()
        assert _outbox(staff['id'], 'match_reminder') == [] and _pushes(staff['id'], 'match_reminder') == []
        assert len(_outbox(member['id'], 'match_reminder')) == 1, 'the member side is still reminded'
        assert _outbox(reader['id'], 'message_reminder') == [] and _pushes(reader['id'], 'message_reminder') == []
    finally:
        _cleanup_inbox(reader)


def test_a_push_that_fails_loses_no_other_push_and_is_tried_again(make_person, on, pushed, monkeypatch):
    """One push raising used to stop the rest of the job's pushes, all of
    them already logged in push_send_log and so never retried, and the tick
    reported an error though its transaction had committed."""
    import service.cron.returnmail as cron
    monkeypatch.setattr(cron, 'JOBS', [('match_reminder', rm.queue_match_reminders)])
    sides = []
    for i in range(3):
        a, b = _person(make_person, f'PushFail{i}'), _person(make_person, f'PushFailB{i}', 'Man')
        _match(a, b, 4)
        with api_tx() as tx:
            tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                          VALUES (%(p)s, %(e)s, 'k', 'a')""", dict(p=a['id'], e=f'https://push.test/{a["id"]}'))
        sides.append(a)
    broken = sides[1]['id']

    def flaky(person_id, title, body, url, kind):
        if person_id == broken:
            raise RuntimeError('push service down')
        pushed.append(dict(person_id=person_id, kind=kind))
    monkeypatch.setattr(rm, '_push', flaky)

    out = cron.tick(TUESDAY)
    assert out['match_reminder'] != 'error', 'the tick reported an error for a job that committed'
    assert sorted(x['person_id'] for x in pushed if x['person_id'] in {s['id'] for s in sides}) == sorted(
        [sides[0]['id'], sides[2]['id']])
    assert _pushes(broken, 'match_reminder') == [], 'a failed push was recorded as sent'
    assert len(_pushes(sides[0]['id'], 'match_reminder')) == 1 and len(_pushes(sides[2]['id'], 'match_reminder')) == 1

    monkeypatch.setattr(rm, '_push', lambda person_id, title, body, url, kind: pushed.append(
        dict(person_id=person_id, kind=kind)))
    pushed.clear()
    cron.tick(TUESDAY)
    assert [x['person_id'] for x in pushed if x['person_id'] in {s['id'] for s in sides}] == [broken]
    assert len(_pushes(broken, 'match_reminder')) == 1


def test_a_reminder_push_still_goes_fire_and_forget_to_every_device(make_person, on, monkeypatch):
    """The quick-question pushes (TEC-1845) send through the same
    _send_to_user_blocking, which now returns a count. The reminders keep
    send_to_user_safe and its thread, and still reach the device."""
    from types import SimpleNamespace

    from service import notifications

    threads: list = []
    sends: list[dict] = []

    class _InlineThread:
        def __init__(self, target=None, kwargs=None, **_ignored):
            threads.append(target)
            self._target, self._kwargs = target, kwargs or {}

        def start(self):
            self._target(**self._kwargs)

    monkeypatch.setattr(notifications, 'threading', SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(notifications, 'PUSH_ENABLED', True)
    monkeypatch.setattr(notifications, '_send_one',
                        lambda endpoint, p256dh, auth, payload: sends.append(payload))
    monkeypatch.setattr(rm, 'PUSH_READY', lambda: True)
    a, b = _person(make_person, 'ThreadA'), _person(make_person, 'ThreadB', 'Man')
    mid = _match(a, b, 4)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(p)s, %(e)s, 'k', 'a')""", dict(p=a['id'], e=f'https://push.test/{a["id"]}'))
    _run()
    assert threads == [notifications._send_to_user_blocking]
    assert [s['title'] for s in sends] == ['Say hello to your match']
    assert _pushes(a['id'], 'match_reminder') == [f'match_reminder-{mid}-d3']
