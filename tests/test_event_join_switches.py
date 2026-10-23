"""The switches for inviting gathering guests who are not members to join
(TEC-1845, docs/superpowers/plans/2026-10-22-events-invite-to-join.md,
Task 2). Both off by default, both passed to the api and the cron, both
counting only while events_live is on. They are deliberately not in
conftest's _EVENT_SWITCH_VARS: tests that want them set them here."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'events_join_block': 'AHAVAH_EVENTS_JOIN_BLOCK_ENABLED',
    'events_join_invite_email': 'AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2


def test_off_by_default(monkeypatch):
    from service.events import switch_on
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    assert not any(switch_on(name) for name in NEW)


@pytest.mark.parametrize('name', sorted(NEW))
def test_each_needs_events_live(monkeypatch, name):
    from service.events import switch_on
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED', raising=False)
    monkeypatch.setenv(NEW[name], '1')
    assert not switch_on(name)
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    assert switch_on(name)


def test_the_invitation_has_a_campaign_switch():
    from service.events import CAMPAIGN_SWITCHES
    assert CAMPAIGN_SWITCHES['event_join_invite'] == 'events_join_invite_email'


def test_the_new_switches_are_not_in_the_events_live_fixture():
    """Existing tests must not see join blocks they do not expect."""
    from tests.conftest import _EVENT_SWITCH_VARS
    assert not set(NEW.values()) & set(_EVENT_SWITCH_VARS)
