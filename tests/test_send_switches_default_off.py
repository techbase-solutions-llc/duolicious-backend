"""A new cron that sends ships switched off (send safeguards plan, 2 Nov
2026, task 5A).

Every cron in service/cron/send_registry.py SENDING_CRONS that is not
grandfathered or owner-only must name a switch from
service/campaigns/switches.py SWITCHES, and docker-compose.production.yml
must pass that switch to the cron container as ${VAR:-0}. switches.enabled()
already reads anything but 1, true, yes or on as off. So a new sending cron
cannot deploy without a switch, and the switch is off until someone sets it
on the droplet.

Static: reads source and YAML only, so this runs in the deploy's rules job.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from send_rules_ast import ROOT  # noqa: E402
from test_cron_send_registry import registry  # noqa: E402

COMPOSE = ROOT / 'docker-compose.production.yml'
SWITCHES_FILE = ROOT / 'service' / 'campaigns' / 'switches.py'


class _Loader(yaml.SafeLoader):
    """The production file uses compose's !reset and !override tags."""


_Loader.add_multi_constructor('!', lambda loader, suffix, node: None)


def switches() -> dict:
    for node in ast.parse(SWITCHES_FILE.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SWITCHES'
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('SWITCHES not found')


def _names(switch) -> list[str]:
    if switch is None:
        return []
    return [switch] if isinstance(switch, str) else list(switch)


def problems(compose_text: str, reg: dict, sw: dict) -> list[str]:
    """Every way the registry and the compose file break the rule."""
    env = (yaml.load(compose_text, Loader=_Loader)['services']['cron'] or {}).get('environment') or {}
    exempt = set(reg['NO_SWITCH_GRANDFATHERED']) | set(reg['OWNER_ONLY'])
    out = []
    for cron, entry in sorted(reg['SENDING_CRONS'].items()):
        if cron in exempt:
            continue
        names = _names(entry.get('switch'))
        if not names:
            out.append(f'{cron} names no switch')
        for name in names:
            var = sw.get(name)
            if var is None:
                out.append(f'{cron}: switch {name} is not in SWITCHES')
                continue
            value = env.get(var)
            if not (isinstance(value, str) and re.fullmatch(r'\$\{' + re.escape(var) + r':-0\}', value)):
                out.append(f'{cron}: the cron container gets {var} as {value!r}, not ${{{var}:-0}}')
    return out


def test_every_new_sending_cron_ships_switched_off():
    found = problems(COMPOSE.read_text(encoding='utf-8'), registry(), switches())
    assert found == [], '\n'.join(found)


def test_a_switch_that_defaults_on_fails():
    text = COMPOSE.read_text(encoding='utf-8').replace(
        '${AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED:-0}', '${AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED:-1}')
    found = problems(text, registry(), switches())
    assert any('AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED' in p for p in found)


def test_a_new_cron_with_no_switch_fails():
    reg = registry()
    reg['SENDING_CRONS'] = dict(reg['SENDING_CRONS'], **{
        'service.cron.newthing': dict(channel='email', dedupe='x', switch=None)})
    found = problems(COMPOSE.read_text(encoding='utf-8'), reg, switches())
    assert 'service.cron.newthing names no switch' in found


def test_a_switch_missing_from_the_cron_container_fails():
    reg = registry()
    reg['SENDING_CRONS'] = dict(reg['SENDING_CRONS'], **{
        'service.cron.newthing': dict(channel='email', dedupe='x', switch='light_sign_in')})
    sw = dict(switches(), light_sign_in='AHAVAH_NOT_IN_COMPOSE_ENABLED')
    found = problems(COMPOSE.read_text(encoding='utf-8'), reg, sw)
    assert any('AHAVAH_NOT_IN_COMPOSE_ENABLED' in p for p in found)
