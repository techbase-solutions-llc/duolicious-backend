"""The send guard's minute tick (send safeguards plan, 2 Nov 2026).

Moves what smtp/guard.py recorded in Redis to Postgres, keeps halts across a
Redis restart, alerts the owner and writes the heartbeat. See
service/sendguard for what each tick does.

`tick` is sync (short transactions and a blocking mail send), so it runs on
a thread here, as the outbox drain does. A tick that raises leaves the
heartbeat stale; print_stacktrace keeps the loop alive, and the watchdog
reads the stale heartbeat from GET /internal/send-stats.
"""
from __future__ import annotations

import asyncio
import random

from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

SENDGUARD_POLL_SECONDS = env_int('DUO_CRON_SENDGUARD_POLL_SECONDS', 60)

print(f'Hello from cron module: {__name__}')


def _tick() -> None:
    from service import sendguard
    out = sendguard.tick()
    if out['alerts']:
        print(f'sendguard: {out}', flush=True)


async def sendguard_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_tick))
        await asyncio.sleep(SENDGUARD_POLL_SECONDS)
