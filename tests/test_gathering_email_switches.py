"""The switches for gatherings in the member emails (TEC-1845): the section
in the weekly community email (E2) and the welcome's mention. Each is off
unless its variable is on, passed to the api and the cron, and counts only
while events_live and events_list are on, since both link to /events."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'e2_gatherings': 'AHAVAH_E2_GATHERINGS_ENABLED',
    'welcome_gatherings': 'AHAVAH_WELCOME_GATHERINGS_ENABLED',
}

_ALL = list(NEW.values()) + ['AHAVAH_EVENTS_LIVE_ENABLED', 'AHAVAH_EVENTS_LIST_ENABLED']


def test_the_switches_and_their_variables():
    assert {k: SWITCHES[k] for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2


def test_off_by_default(monkeypatch):
    from service.events import member_email_on
    for env in _ALL:
        monkeypatch.delenv(env, raising=False)
    assert not member_email_on('e2_gatherings')
    assert not member_email_on('welcome_gatherings')


@pytest.mark.parametrize('name', sorted(NEW))
def test_both_need_events_live_and_the_list(monkeypatch, name):
    from service.events import member_email_on
    for env in _ALL:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv(NEW[name], '1')
    assert not member_email_on(name)
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    assert not member_email_on(name)
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    assert member_email_on(name)
    # The own switch reads as enabled() reads it: stray spaces are trimmed,
    # anything that is not a plain yes is off.
    monkeypatch.setenv(NEW[name], '1 ')
    assert member_email_on(name)
    monkeypatch.setenv(NEW[name], 'maybe')
    assert not member_email_on(name)
    # The other email's switch is its own.
    other = next(n for n in NEW if n != name)
    assert not member_email_on(other)
