"""The cron that sends the held Wave 3 mail runs every job whose switch is
on, and sends nothing while every switch is off."""
from datetime import datetime, timezone

from service.campaigns.switches import SWITCHES

THURSDAY = datetime(2026, 10, 15, 13, tzinfo=timezone.utc)


def test_every_switch_is_off_unless_set(monkeypatch):
    from service.campaigns.switches import enabled
    for name, env in SWITCHES.items():
        monkeypatch.delenv(env, raising=False)
        assert enabled(name) is False
        for off in ('', '0', 'false', 'no', 'off', 'ture'):
            monkeypatch.setenv(env, off)
            assert enabled(name) is False, f'{env}={off!r} read as on'
        monkeypatch.setenv(env, 'yes')
        assert enabled(name) is True


def test_a_tick_runs_each_job_and_reports_what_it_queued(monkeypatch):
    import service.cron.returnmail as rm
    calls = []
    monkeypatch.setattr(rm, 'JOBS', [('a', lambda tx, now: calls.append(('a', now)) or 2),
                                     ('b', lambda tx, now: calls.append(('b', now)) or 0)])
    out = rm.tick(THURSDAY)
    assert [c[0] for c in calls] == ['a', 'b']
    assert out == {'a': 2, 'b': 0}


def test_one_failing_job_does_not_stop_the_others(monkeypatch):
    import service.cron.returnmail as rm
    def boom(tx, now):
        raise RuntimeError('boom')
    monkeypatch.setattr(rm, 'JOBS', [('bad', boom), ('good', lambda tx, now: 1)])
    out = rm.tick(THURSDAY)
    assert out['good'] == 1 and out['bad'] == 'error'


def test_the_held_jobs_are_registered():
    import service.cron.returnmail as rm
    names = [name for name, _ in rm.JOBS]
    for job in ('likes_waiting', 'match_reminder', 'message_reminder', 'profile_views'):
        assert job in names


def test_the_compose_file_passes_every_switch_to_the_cron_and_defaults_off():
    import pathlib
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    for env in SWITCHES.values():
        assert f'{env}: ${{{env}:-0}}' in text, f'{env} is not passed through, defaulting to 0'
