"""The send guard (send safeguards plan, 2 Nov 2026, task 1).

Every email ends in `Smtp.send` and every web push in `_send_one`, so the
gate sits there. These tests use the fakeredis client the autouse fixture in
conftest installs, and patch `Smtp._try_send` so nothing leaves the
container. Nothing here reads or writes production."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

import smtp as smtp_mod
from smtp import guard


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch):
    """Every message that reached the provider, as (to, subject)."""
    out: list[tuple[str, str]] = []

    def _try_send(self, **kw):
        out.append((kw['to_addr'], kw['subject']))
        return f'mid-{len(out)}'

    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', _try_send)
    return out


def _mailer():
    return smtp_mod.make_aws_smtp()


def _send(to, kind='profile_resting', subject='Your Ahavah profile is resting', **kw):
    return _mailer().send(subject=subject, body='<p>x</p>', to_addr=to, kind=kind,
                          retries=0, backoff=0, **kw)


def _events():
    return [json.loads(e) for e in reversed(guard._redis().lrange('sg:events', 0, -1))]


def _events_of(name):
    return [e for e in _events() if e['event'] == name]


# ---------------------------------------------------------------------------
# per-person limits
# ---------------------------------------------------------------------------

def test_the_fourth_same_kind_email_to_one_person_in_24_hours_is_refused(sent):
    for _ in range(4):
        _send('loop@ahavah-test.invalid')
    assert len(sent) == 3
    refused = _events_of('refused')
    assert len(refused) == 1 and refused[0]['rule'] == 'per_kind'
    assert '@' not in json.dumps(_events())


def test_the_limit_is_a_rolling_24_hours_from_the_first_send(sent):
    with freeze_time('2026-11-03 12:00:00'):
        for _ in range(3):
            _send('day@ahavah-test.invalid')
    with freeze_time('2026-11-04 12:01:00'):
        _send('day@ahavah-test.invalid')
    assert len(sent) == 4


def test_a_bulk_kind_reaches_one_person_once_in_24_hours(sent):
    _send('weekly@ahavah-test.invalid', kind='e2', subject='This week on Ahavah')
    _send('weekly@ahavah-test.invalid', kind='e2', subject='This week on Ahavah')
    assert len(sent) == 1
    assert _events_of('refused')[0]['rule'] == 'bulk_repeat'


def test_a_send_marked_bulk_reaches_one_person_once_in_24_hours(sent):
    _send('list@ahavah-test.invalid', kind='some_list', bulk=True)
    _send('list@ahavah-test.invalid', kind='some_list', bulk=True)
    assert len(sent) == 1


def test_chat_message_email_allows_10_a_day(sent):
    for _ in range(11):
        _send('chatty@ahavah-test.invalid', kind='message', subject='You have a new message on Ahavah')
    assert len(sent) == 10


def test_twelve_non_essential_emails_of_any_kind_then_refused(sent):
    for i in range(13):
        _send('busy@ahavah-test.invalid', kind=f'kind_{i}', subject=f'Subject {i}')
    assert len(sent) == 12
    assert _events_of('refused')[0]['rule'] == 'per_person_all'


def test_owner_addresses_take_50_of_a_kind(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_OWNER_ADDRESSES', 'owner@ahavah-test.invalid')
    for _ in range(51):
        _send('Owner@ahavah-test.invalid', kind='report', subject='A new report')
    assert len(sent) == 50


def test_a_missing_kind_comes_from_the_subject_with_digits_folded():
    a = guard.derive_kind('You have 3 new likes')
    b = guard.derive_kind('You have  12 new LIKES ')
    c = guard.derive_kind('Something else')
    assert a == b != c
    assert a.startswith('subj:') and len(a) == len('subj:') + 12


def test_a_subject_with_a_count_in_it_is_still_one_kind(sent):
    for n in range(5):
        _mailer().send(subject=f'You have {n} new likes', body='x', to_addr='likes@ahavah-test.invalid',
                       retries=0, backoff=0)
    assert len(sent) == 3


# ---------------------------------------------------------------------------
# alerts on refusal and the kind halt
# ---------------------------------------------------------------------------

def test_the_first_refusal_of_a_kind_each_barbados_day_is_an_alert(sent):
    with freeze_time('2026-11-03 14:00:00'):
        for _ in range(5):
            _send('a@ahavah-test.invalid')
    refused = _events_of('refused')
    assert [e['alert'] for e in refused] == [True, False]
    # 03:59 UTC on 4 Nov is still 3 Nov in Barbados: no new alert.
    with freeze_time('2026-11-04 03:59:00'):
        _send('b@ahavah-test.invalid')
        for _ in range(3):
            _send('b@ahavah-test.invalid')
    assert [e['alert'] for e in _events_of('refused')] == [True, False, False]
    # 04:01 UTC on 5 Nov is 5 Nov in Barbados (00:01): alerts again.
    with freeze_time('2026-11-05 04:01:00'):
        for _ in range(4):
            _send('c@ahavah-test.invalid')
    assert [e['alert'] for e in _events_of('refused')][-1] is True


def test_three_people_tripping_one_kind_within_an_hour_halt_it_for_everyone(sent):
    for who in ('p1', 'p2', 'p3'):
        for _ in range(4):
            _send(f'{who}@ahavah-test.invalid')
    halts = _events_of('halt')
    assert len(halts) == 1 and halts[0]['kind'] == 'profile_resting' and halts[0]['alert']
    before = len(sent)
    _send('fourth@ahavah-test.invalid')
    assert len(sent) == before
    assert _events_of('refused')[-1]['rule'] == 'halt_kind'
    # Another kind still goes.
    _send('fourth@ahavah-test.invalid', kind='welcome', subject='Welcome')
    assert len(sent) == before + 1


def test_a_halt_stays_until_cleared(sent):
    guard.set_halt('email', 'profile_resting', reason='test')
    with freeze_time(datetime.now(timezone.utc) + timedelta(days=40)):
        _send('later@ahavah-test.invalid')
        assert sent == []
        assert guard.clear_halt_redis('email', 'profile_resting')
        _send('later@ahavah-test.invalid')
        assert len(sent) == 1


def test_every_refusal_prints_one_mail_guard_line(sent, capsys):
    for _ in range(4):
        _send('log@ahavah-test.invalid')
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith('MAIL_GUARD ')]
    assert len(lines) == 1
    assert json.loads(lines[0][len('MAIL_GUARD '):])['rule'] == 'per_kind'


# ---------------------------------------------------------------------------
# atomic counting
# ---------------------------------------------------------------------------

def test_ten_threads_at_once_let_exactly_three_through(sent):
    barrier = threading.Barrier(10)

    def go():
        barrier.wait()
        _send('race@ahavah-test.invalid')

    threads = [threading.Thread(target=go) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sent) == 3


def test_a_send_that_fails_after_its_retries_still_counts(monkeypatch):
    def _boom(self, **kw):
        raise RuntimeError('provider down')

    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', _boom)
    for _ in range(3):
        assert _send('fail@ahavah-test.invalid') is None
    calls = []
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', lambda self, **kw: calls.append(kw) or 'mid')
    _send('fail@ahavah-test.invalid')
    assert calls == []


# ---------------------------------------------------------------------------
# global ceilings and the trial week
# ---------------------------------------------------------------------------

def _flood(n, kind_prefix='g'):
    for i in range(n):
        _send(f'{kind_prefix}{i}@ahavah-test.invalid', kind=f'{kind_prefix}_kind', subject='Hello')


def test_before_the_shadow_date_the_hourly_ceiling_alerts_and_refuses_nothing(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '5')
    monkeypatch.setenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', '2026-11-10')
    with freeze_time('2026-11-03 14:00:00'):
        _flood(8)
    assert len(sent) == 8
    ceil = _events_of('ceiling_shadow')
    assert len(ceil) == 1 and ceil[0]['alert']
    assert guard._redis().get('sg:halt:all') is None


def test_on_the_shadow_date_the_hourly_ceiling_halts_non_essential_mail(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '5')
    monkeypatch.setenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', '2026-11-03')
    with freeze_time('2026-11-03 14:00:00'):
        _flood(8)
    assert len(sent) == 5
    assert guard._redis().get('sg:halt:all') is not None
    assert len(_events_of('halt')) == 1


@pytest.mark.parametrize('value', [None, '', 'next tuesday', '2026-13-45'])
def test_a_missing_or_garbled_shadow_date_enforces(sent, monkeypatch, value):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '5')
    if value is None:
        monkeypatch.delenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', raising=False)
    else:
        monkeypatch.setenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', value)
    _flood(8)
    assert len(sent) == 5


def test_the_daily_ceiling_counts_a_barbados_day(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_DAY', '6')
    monkeypatch.delenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', raising=False)
    with freeze_time('2026-11-03 10:00:00'):
        _flood(4, 'd1_')
    with freeze_time('2026-11-03 20:00:00'):
        _flood(4, 'd2_')
    assert len(sent) == 6


def test_a_bulk_window_raises_the_hourly_ceiling(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '5')
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR_BULK', '20')
    with freeze_time('2026-11-03 14:00:00'):
        monkeypatch.setenv('AHAVAH_SEND_GUARD_BULK_UNTIL', '2026-11-03T13:00:00')  # Barbados, 17:00 UTC
        _flood(8)
    assert len(sent) == 8


def test_a_bulk_window_more_than_24_hours_ahead_is_ignored_and_alerts(sent, monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '5')
    with freeze_time('2026-11-03 14:00:00'):
        monkeypatch.setenv('AHAVAH_SEND_GUARD_BULK_UNTIL', '2026-11-06T13:00:00')
        _flood(8)
    assert len(sent) == 5
    assert len(_events_of('bulk_window_ignored')) == 1


# ---------------------------------------------------------------------------
# essential codes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('kind', ['sign_in_code', 'change_email_code'])
def test_codes_pass_every_halt_and_ceiling(sent, monkeypatch, kind):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '0')
    guard.set_halt('email', None, reason='test')
    guard.set_halt('email', kind, reason='test')
    _send('code@ahavah-test.invalid', kind=kind, subject='Sign in to Ahavah')
    assert len(sent) == 1


@pytest.mark.parametrize('kind', ['sign_in_code', 'change_email_code'])
def test_the_26th_code_in_24_hours_is_refused_and_every_refusal_alerts(sent, kind):
    for _ in range(27):
        _send('codes@ahavah-test.invalid', kind=kind, subject='Sign in to Ahavah')
    assert len(sent) == 25
    caps = _events_of('essential_cap')
    assert len(caps) == 2 and all(e['alert'] for e in caps)


def test_send_otp_passes_the_kind_its_caller_gives(monkeypatch):
    import service.person as person
    calls = []
    monkeypatch.setattr(person.aws_smtp, 'send', lambda **kw: calls.append(kw))
    monkeypatch.setattr(guard, 'spawn', lambda fn, *a, **k: fn(*a, **k))
    person._send_otp('member@ahavah-test.invalid', '123456', kind='change_email_code')
    person._send_otp('member@ahavah-test.invalid', '123456', kind='sign_in_code')
    assert [c['kind'] for c in calls] == ['change_email_code', 'sign_in_code']


# ---------------------------------------------------------------------------
# Redis down
# ---------------------------------------------------------------------------

class _DeadRedis:
    def __getattr__(self, name):
        def _raise(*a, **k):
            raise ConnectionError('redis is down')
        return _raise


def test_redis_down_falls_back_to_in_process_counters_and_records_it(sent, monkeypatch):
    monkeypatch.setattr(guard, '_redis_client', _DeadRedis())
    for _ in range(4):
        _send('nored@ahavah-test.invalid')
    assert len(sent) == 3
    assert any(e['event'] == 'redis_down' for e in guard.drain_local_events())


def test_both_stores_down_refuses_non_essential_and_allows_codes(sent, monkeypatch):
    monkeypatch.setattr(guard, '_redis_client', _DeadRedis())

    def _broken(*a, **k):
        raise RuntimeError('local store broken')

    monkeypatch.setattr(guard._LocalStore, 'incr_many', _broken)
    monkeypatch.setattr(guard._LocalStore, 'get_many', _broken)
    _send('x@ahavah-test.invalid')
    _send('x@ahavah-test.invalid', kind='sign_in_code', subject='Sign in to Ahavah')
    assert sent == [('x@ahavah-test.invalid', 'Sign in to Ahavah')]


# ---------------------------------------------------------------------------
# the dry-run tripwire
# ---------------------------------------------------------------------------

def test_no_send_makes_smtp_send_raise_and_record(sent):
    with guard.no_send():
        with pytest.raises(guard.SendDuringDryRun):
            _send('dry@ahavah-test.invalid')
    assert sent == []
    ev = _events_of('dry_run_send')
    assert len(ev) == 1 and ev[0]['alert'] and ev[0]['channel'] == 'email'


def test_no_send_reaches_a_thread_started_with_spawn(sent):
    caught = []

    def work():
        try:
            _send('thread@ahavah-test.invalid')
        except guard.SendDuringDryRun:
            caught.append(True)

    with guard.no_send():
        t = guard.spawn(work)
    t.join()
    assert caught == [True] and sent == []


def test_no_send_in_one_asyncio_task_does_not_touch_another(sent):
    results = {}

    async def dry():
        with guard.no_send():
            await asyncio.sleep(0.01)
            try:
                await asyncio.to_thread(_send, 'dry2@ahavah-test.invalid')
            except guard.SendDuringDryRun:
                results['dry'] = 'refused'

    async def live():
        await asyncio.sleep(0.005)
        await asyncio.to_thread(_send, 'live@ahavah-test.invalid')
        results['live'] = 'sent'

    async def main():
        await asyncio.gather(dry(), live())

    asyncio.run(main())
    assert results == {'dry': 'refused', 'live': 'sent'}
    assert sent == [('live@ahavah-test.invalid', 'Your Ahavah profile is resting')]


def test_no_send_makes_send_one_raise_and_record(monkeypatch):
    import service.notifications as n
    calls = []
    monkeypatch.setattr('pywebpush.webpush', lambda **kw: calls.append(kw))
    with guard.no_send():
        with pytest.raises(guard.SendDuringDryRun):
            n._send_one('https://push.test/x', 'k', 'a', {'title': 't', 'tag': 'x'})
    assert calls == []
    assert _events_of('dry_run_send')[0]['channel'] == 'push'


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------

def test_push_kind_comes_from_the_tag_never_the_title():
    a = guard.push_kind({'title': 'Anna liked you', 'tag': 'like-12'})
    b = guard.push_kind({'title': 'Ben liked you', 'tag': 'like-345'})
    assert a == b and a.startswith('tag:')
    assert guard.push_kind({'title': 'Anna wrote to you'}) == 'push:untagged'
    assert guard.push_kind({'title': 'Ben wrote to you'}) == 'push:untagged'


def test_the_21st_non_chat_push_to_one_person_in_24_hours_is_refused():
    allowed = 0
    for i in range(21):
        try:
            guard.check_push(42, f'kind_{i}')
            allowed += 1
        except guard.MailGuardRefused as e:
            assert e.rule == 'per_person_all'
    assert allowed == 20


def test_the_7th_same_kind_push_is_refused_and_chat_allows_100():
    ok = 0
    for _ in range(7):
        try:
            guard.check_push(43, 'reminder')
            ok += 1
        except guard.MailGuardRefused:
            pass
    assert ok == 6
    ok = 0
    for _ in range(101):
        try:
            guard.check_push(43, 'chat_message')
            ok += 1
        except guard.MailGuardRefused:
            pass
    assert ok == 100


def test_a_refused_push_reaches_no_device_and_prunes_nothing(monkeypatch):
    import service.notifications as n
    monkeypatch.setattr(n, 'PUSH_ENABLED', True)
    hits = []
    monkeypatch.setattr(n, '_send_one', lambda *a, **k: hits.append(a))
    guard.set_halt('push', 'reminder', reason='test')
    assert n._send_to_user_blocking(999999, {'title': 't', 'tag': 'r'}, kind='reminder') == 0
    assert hits == []


def test_the_global_push_ceiling_counts_each_device_send(monkeypatch):
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_PUSH_GLOBAL_HOUR', '3')
    monkeypatch.delenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', raising=False)
    import service.notifications as n
    calls = []
    monkeypatch.setattr('pywebpush.webpush', lambda **kw: calls.append(kw))
    results = [n._send_one(f'https://push.test/{i}', 'k', 'a', {'tag': 'x'}) for i in range(5)]
    assert len(calls) == 3
    assert results[3:] == ['refused', 'refused']


# ---------------------------------------------------------------------------
# the gate's own alert
# ---------------------------------------------------------------------------

def test_guard_alert_passes_a_halt_and_its_21st_in_a_day_is_refused(sent, monkeypatch):
    guard.set_halt('email', None, reason='test')
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '0')
    for _ in range(21):
        _send('admin@techbaseltd.com', kind='guard_alert', subject='Ahavah mail guard: 1 alert')
    assert len(sent) == 20


# ---------------------------------------------------------------------------
# the incident, replayed
# ---------------------------------------------------------------------------

def test_replay_of_the_resting_email_loop(sent, monkeypatch):
    """The deployed maybe_send_email, every 10 simulated minutes, for 14
    addresses: each gets 3, the first refusal alerts, then the kind halts."""
    import service.cron.autodeactivate2 as job
    monkeypatch.setattr(job, 'aws_smtp', _mailer())
    people = [f'resting{i}@ahavah-test.invalid' for i in range(14)]
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    for tick in range(12):
        with freeze_time(start + timedelta(minutes=10 * tick)):
            for p in people:
                job.maybe_send_email(p)
    per_person = {p: sum(1 for to, _ in sent if to == p) for p in people}
    assert set(per_person.values()) <= {3} | {0}
    assert max(per_person.values()) == 3
    assert len(sent) <= 3 * 14
    refused = _events_of('refused')
    assert refused and refused[0]['alert'] is True
    halts = _events_of('halt')
    assert len(halts) == 1 and halts[0]['kind'] == 'profile_resting'


# ---------------------------------------------------------------------------
# every cron with a DRY_RUN runs its _once() inside no_send()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('module,once', [
    ('service.cron.photocleaner', 'clean_photos_once'),
    ('service.cron.audiocleaner', 'clean_audio_once'),
    ('service.cron.checkphotos', 'check_photos_once'),
])
@pytest.mark.parametrize('flag', [True, False])
def test_each_dry_run_cron_runs_inside_the_tripwire(monkeypatch, module, once, flag):
    import importlib
    mod = importlib.import_module(module)
    seen = []

    async def body():
        seen.append(guard.in_no_send())

    monkeypatch.setattr(mod, 'DRY_RUN', flag)
    monkeypatch.setattr(mod, f'_{once}', body)
    asyncio.run(getattr(mod, once)())
    assert seen == [flag]


# ---------------------------------------------------------------------------
# failed sends (task 6)
# ---------------------------------------------------------------------------

def _tally(kind, outcome):
    vals = guard._redis().hgetall(f'sg:tally:{guard.utc_hour()}')
    return int(vals.get(f'email|{kind}|{outcome}', 0))


def _down(monkeypatch):
    def _boom(self, **kw):
        raise RuntimeError('provider down')
    monkeypatch.setattr(smtp_mod.Smtp, '_try_send', _boom)


def test_a_failed_send_returns_none_by_default_and_is_counted_failed(monkeypatch):
    _down(monkeypatch)
    assert _send('down@ahavah-test.invalid', kind='receipt', subject='Your receipt') is None
    assert _tally('receipt', 'failed') == 1 and _tally('receipt', 'sent') == 0


def test_raise_on_failure_raises_send_failed_and_counts_once(monkeypatch):
    _down(monkeypatch)
    with pytest.raises(guard.SendFailed):
        _send('down2@ahavah-test.invalid', kind='receipt', subject='Your receipt', raise_on_failure=True)
    assert _tally('receipt', 'failed') == 1


def test_a_success_is_counted_sent(sent):
    _send('ok@ahavah-test.invalid', kind='receipt', subject='Your receipt')
    assert _tally('receipt', 'sent') == 1 and _tally('receipt', 'failed') == 0


# ---------------------------------------------------------------------------
# review of 2 Nov 2026
# ---------------------------------------------------------------------------

def test_untagged_pushes_of_different_events_never_share_a_limit(monkeypatch):
    """Profile view, verification and reminder pushes carry no tag, and all
    counted as push:untagged: 3 members over 6 profile view pushes in an
    hour halted verification results for everyone. Without a kind or a tag,
    the event names the push."""
    import service.notifications as n
    monkeypatch.setattr(n, 'PUSH_ENABLED', True)
    monkeypatch.setattr(n, '_allowed_for_event', lambda person_id, event_kind: True)

    def _blocking(person_id, payload, kind=None):
        try:
            guard.check_push(person_id, kind or guard.push_kind(payload))
            return 1
        except guard.MailGuardRefused:
            return 0

    monkeypatch.setattr(n, '_send_to_user_blocking', _blocking)
    for person in (1, 2, 3):
        for _ in range(7):
            n.send_to_user_counted(person, 'Someone viewed your profile', 'b', event_kind='profile_view')
    assert [e['kind'] for e in _events_of('halt')] == ['event:profile_view']
    assert n.send_to_user_counted(4, 'You are verified', 'b', event_kind='verification') == 1


def test_a_push_names_its_kind_by_caller_then_tag_then_event(monkeypatch):
    import service.notifications as n
    monkeypatch.setattr(n, 'PUSH_ENABLED', True)
    monkeypatch.setattr(n, '_allowed_for_event', lambda person_id, event_kind: True)
    seen = []
    monkeypatch.setattr(n, '_send_to_user_blocking',
                        lambda person_id, payload, kind=None: seen.append(kind) or 1)
    n.send_to_user_counted(7, 't', 'b', event_kind='verification')
    n.send_to_user_counted(7, 't', 'b', tag='match:12', event_kind='match')
    n.send_to_user_counted(7, 't', 'b', event_kind='questions', kind='own')
    assert seen == ['event:verification', None, 'own']


@pytest.mark.parametrize('fn, extra', [
    ('enqueue', dict(person_id=1, unsub_scope='news')),
    ('enqueue_for_lead', dict(lead_id=1)),
    ('enqueue_for_organiser', dict(organiser_id=1)),
    ('enqueue_for_recommendation', dict(recommendation_id=1)),
    ('enqueue_for_mentor_link', dict(mentor_link_id=1)),
    ('enqueue_for_onboardee', dict()),
])
def test_a_dry_run_cannot_queue_mail_for_the_drain_to_send_later(fn, extra):
    """The drain runs outside the trial run's no_send(), so a row queued in
    a dry run would be sent a minute later. Queueing raises and alerts."""
    from service.campaigns import outbox

    class _Tx:
        def execute(self, *a, **k):
            raise AssertionError('a dry run wrote to the outbox')

    with guard.no_send():
        with pytest.raises(guard.SendDuringDryRun):
            getattr(outbox, fn)(_Tx(), campaign='c', campaign_id='1', email='q@ahavah-test.invalid',
                                subject='s', html='h', from_addr=None, **extra)
    ev = _events_of('dry_run_send')
    assert len(ev) == 1 and ev[0]['alert'] is True and ev[0]['kind'] == 'c'


def test_a_loop_refused_for_one_person_never_tips_everyone_into_a_global_halt(sent, monkeypatch):
    """A loop to one person is refused from its 4th copy. Its refused copies
    used to count towards the global ceilings, so after the trial week a
    tight loop to one person halted every member's mail."""
    monkeypatch.delenv('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', raising=False)
    monkeypatch.setenv('AHAVAH_SEND_GUARD_LIMIT_EMAIL_GLOBAL_HOUR', '20')
    for _ in range(50):
        _send('stuck@ahavah-test.invalid')
    _send('someone-else@ahavah-test.invalid', kind='welcome', subject='Welcome to Ahavah')
    assert len(sent) == 4
    assert _events_of('halt') == []


def test_refused_copies_of_one_kind_leave_that_person_their_other_mail(sent):
    for _ in range(20):
        _send('loop-two@ahavah-test.invalid')
    _send('loop-two@ahavah-test.invalid', kind='receipt', subject='Your receipt')
    assert len(sent) == 4


def test_a_refused_push_leaves_that_person_their_other_pushes():
    for _ in range(30):
        try:
            guard.check_push(44, 'reminder')
        except guard.MailGuardRefused:
            pass
    guard.check_push(44, 'event:verification')   # raises if the 24 refused reminders were counted
