"""pushcomposer - sends the pushes composed on the Growth tab (TEC-2182;
service/notifications/composer.py).

Every 10 minutes, one pass of every send that is due. Nothing at all while
AHAVAH_PUSH_COMPOSER_ENABLED is off. Each member is claimed in
push_send_log before their push, so a repeat tick, a restart or two passes
at once push nobody twice, and a send row is one pass over its frozen
audience, never a loop.
"""
from __future__ import annotations

import asyncio
import random

from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.notifications import composer

PUSH_COMPOSER_POLL_SECONDS = env_int('DUO_CRON_PUSH_COMPOSER_POLL_SECONDS', 10 * 60)

print(f'Hello from cron module: {__name__}')


def tick() -> dict:
    out = composer.tick()
    if out:
        print(f'push_composer: {out}', flush=True)
    return out


async def push_composer_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(tick))
        await asyncio.sleep(PUSH_COMPOSER_POLL_SECONDS)
