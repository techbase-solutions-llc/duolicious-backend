"""The gathering switches (TEC-1845). events_live keeps the whole release
dark; each surface and each email has its own switch and needs events_live
too. Every variable is passed to the api and the cron, defaulting to 0."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'events_live': 'AHAVAH_EVENTS_LIVE_ENABLED',
    'events_hosting': 'AHAVAH_EVENTS_HOSTING_ENABLED',
    'events_list': 'AHAVAH_EVENTS_LIST_ENABLED',
    'events_invite': 'AHAVAH_EVENTS_INVITE_ENABLED',
    'events_confirm_email': 'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED',
    'events_reminder_email': 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED',
    'events_change_email': 'AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED',
    'events_cancel_email': 'AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED',
    'events_digest_email': 'AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED',
    'events_manage_email': 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED',
}

def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW

@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2

def test_everything_needs_the_live_switch(monkeypatch):
    from service.events import live, surface_on, switch_on
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED', '1')
    assert not live() and not surface_on('events_list') and not switch_on('events_confirm_email')
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    assert live() and surface_on('events_list') and switch_on('events_confirm_email')
    assert not surface_on('events_hosting') and not switch_on('events_digest_email')

def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/events/status')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'live': False, 'hosting': False, 'list': False, 'invite': False}
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_EVENTS_INVITE_ENABLED', '1')
    assert client.get('/events/status').get_json() == {'live': True, 'hosting': False, 'list': False, 'invite': True}
