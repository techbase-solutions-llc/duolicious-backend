"""Every container that sends a push is given the VAPID keys.

PUSH_ENABLED in service/notifications/__init__.py is true only when both
keys are set, and is false without a word otherwise. The chat container
sends the push for each new message (service/chat/messagestorage) but was
never given the keys, so from launch until 25 Nov 2026 no member got a
push for a chat message while every other push worked.

Static: reads YAML only, so this runs in the deploy's rules job.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / 'docker-compose.production.yml'

# The containers that send pushes: api (likes, matches, verification),
# cron (reminders, questions, composer) and chat (new messages).
SENDERS = ('api', 'cron', 'chat')
KEYS = ('VAPID_PUBLIC_KEY', 'VAPID_PRIVATE_KEY', 'VAPID_SUBJECT')


class _Loader(yaml.SafeLoader):
    """The production file uses compose's !reset and !override tags."""


_Loader.add_multi_constructor('!', lambda loader, suffix, node: None)


def missing(compose_text: str) -> list[str]:
    services = yaml.load(compose_text, Loader=_Loader)['services']
    out = []
    for name in SENDERS:
        env = (services.get(name) or {}).get('environment') or {}
        for key in KEYS:
            if env.get(key) != '${' + key + '}':
                out.append(f'{name}: {key}')
    return out


def test_every_push_sender_has_the_keys():
    assert missing(COMPOSE.read_text(encoding='utf-8')) == []


def test_a_sender_without_the_keys_is_caught():
    text = COMPOSE.read_text(encoding='utf-8')
    services = yaml.load(text, Loader=_Loader)['services']
    assert 'chat' in services
    broken = text.replace('      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}\n', '', 1)
    assert missing(broken) != []
