"""The matchmaker switches (TEC-1845). matchmaker_live keeps the whole
release dark; each surface, email and push has its own switch and needs
matchmaker_live too. Every variable is passed to the api and the cron,
defaulting to 0."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'matchmaker_live': 'AHAVAH_MATCHMAKER_LIVE_ENABLED',
    'matchmaker_alerts': 'AHAVAH_MATCHMAKER_ALERTS_ENABLED',
    'matchmaker_visitor_alerts': 'AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED',
    'matchmaker_introductions': 'AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED',
    'matchmaker_mentors': 'AHAVAH_MATCHMAKER_MENTORS_ENABLED',
    'matchmaker_alert_email': 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED',
    'matchmaker_visitor_confirm_email': 'AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED',
    'matchmaker_visitor_alert_email': 'AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED',
    'matchmaker_recommend_email': 'AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED',
    'matchmaker_intro_email': 'AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED',
    'matchmaker_mentor_invite_email': 'AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED',
    'matchmaker_alert_push': 'AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED',
    'matchmaker_intro_push': 'AHAVAH_MATCHMAKER_INTRO_PUSH_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2


def test_everything_needs_the_live_switch(monkeypatch):
    from service.matchmaker import live, surface_on, switch_on
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_MATCHMAKER_ALERTS_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED', '1')
    assert not live() and not surface_on('matchmaker_alerts') and not switch_on('matchmaker_alert_email')
    monkeypatch.setenv('AHAVAH_MATCHMAKER_LIVE_ENABLED', '1')
    assert live() and surface_on('matchmaker_alerts') and switch_on('matchmaker_alert_email')
    assert not surface_on('matchmaker_mentors')


def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/matchmaker/status')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'live': False, 'alerts': False, 'visitor_alerts': False,
                            'introductions': False, 'mentors': False}
    monkeypatch.setenv('AHAVAH_MATCHMAKER_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MATCHMAKER_MENTORS_ENABLED', '1')
    assert client.get('/matchmaker/status').get_json()['mentors'] is True


def test_the_address_key_is_keyed_not_a_plain_hash():
    import hashlib
    from service.matchmaker import address_key
    assert address_key('hannah@example.com') != hashlib.sha256(b'hannah@example.com').hexdigest()
    assert address_key('hannah@example.com') == address_key('hannah@example.com')


def _is_matchmaker_rule(rule: str) -> bool:
    import re
    return (rule.startswith(('/matchmaker', '/alerts', '/introductions', '/recommendations', '/mentor'))
            or bool(re.match(r'^/conversations/<[^>]+>/(share|sharing)$', rule))
            or bool(re.match(r'^/matches/<[^>]+>/mentor-note$', rule)))


def test_every_matchmaker_route_answers_404_while_dark(app, client, monkeypatch):
    """Global constraint: while matchmaker_live is off, every matchmaker
    route but GET /matchmaker/status answers 404, whatever the body or
    headers."""
    for env in NEW.values():
        monkeypatch.setenv(env, '1')
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    seen = []
    for rule in app.url_map.iter_rules():
        if not _is_matchmaker_rule(rule.rule):
            continue
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f'<int:{arg}>', '1').replace(f'<{arg}>', '00000000-0000-0000-0000-000000000000')
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            if (method, rule.rule) == ('GET', '/matchmaker/status'):
                continue
            r = client.open(path, method=method, json={'email': 'x@ahavah-test.invalid'},
                            headers={'X-Mentor-Token': 'x' * 32})
            seen.append((method, rule.rule))
            assert r.status_code == 404, (method, rule.rule, r.status_code)
    assert len(seen) >= 30, seen
