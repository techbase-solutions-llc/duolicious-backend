"""The Together switches (TEC-1845).

together_live keeps the whole release dark until launch, as questions_live
did for the quick questions. Each email has its own switch and needs
together_live too. Each variable is passed through to both the api and the
cron containers, defaulting to 0: without the pass-through a switch can
never be turned on.
"""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'together_live': 'AHAVAH_TOGETHER_LIVE_ENABLED',
    'together_invite_email': 'AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED',
    'together_answered_email': 'AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED',
    'together_ready_email': 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
    'together_summary_email': 'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED',
    'release4_together': 'AHAVAH_RELEASE4_TOGETHER_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2, (
        f'{env} must be passed through in both the api and the cron blocks, defaulting to 0')


def test_each_send_needs_the_live_switch(monkeypatch):
    from service.tools import live, switch_on
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    assert live() is False and switch_on('together_invite_email') is False
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    assert live() is True and switch_on('together_invite_email') is True
    assert switch_on('together_ready_email') is False


def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/tools/status')
    assert r.status_code == 200
    assert r.get_json() == {'live': False, 'invite_email': False, 'release4_together': False}
    assert r.headers['Cache-Control'] == 'no-store'
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    assert client.get('/tools/status').get_json() == {'live': True, 'invite_email': True,
                                                      'release4_together': False}


def test_status_reports_release_4_together_only_once_together_is_live(client, monkeypatch):
    """release4_together keeps Chat > More's checklist and the past results
    dark (TEC-1845, in-app plan release 4). It counts only once Together is
    live, as the email switches do."""
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_RELEASE4_TOGETHER_ENABLED', '1')
    assert client.get('/tools/status').get_json()['release4_together'] is False
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    assert client.get('/tools/status').get_json()['release4_together'] is True
    monkeypatch.delenv('AHAVAH_RELEASE4_TOGETHER_ENABLED')
    assert client.get('/tools/status').get_json()['release4_together'] is False
