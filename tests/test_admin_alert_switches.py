"""The owner alert switches (TEC-1897). The stale-post email and the
adminalerts cron are each off unless their variable is on, and each variable
is passed through to the api and the cron containers, defaulting to 0.

The report email has no variable: it is live (17db55a), and the owner's
"Email me when a report arrives" preference is its switch."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES, enabled

NEW = {
    'stale_post_alert': 'AHAVAH_STALE_POST_ALERT_ENABLED',
    'admin_alerts_cron': 'AHAVAH_ADMIN_ALERTS_CRON_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW
    assert 'report_alert' not in SWITCHES


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2


def test_each_is_off_until_its_variable_is_on(monkeypatch):
    for name, env in NEW.items():
        monkeypatch.delenv(env, raising=False)
        assert enabled(name) is False
        monkeypatch.setenv(env, 'on')
        assert enabled(name) is True
        monkeypatch.setenv(env, 'onn')
        assert enabled(name) is False
