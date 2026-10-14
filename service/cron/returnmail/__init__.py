"""returnmail - sends the mail held for the owner's proof (health review,
13 Oct 2026, Wave 3): the reasons a member has to come back.

Each job is one module's `queue_due(tx, now)`. A job does nothing while its
switch is off (service/campaigns/switches.py, all off by default) or outside
its own window (service/campaigns/held.py), so this cron runs harmlessly on
every deploy and sends nothing until the owner has confirmed a proof and the
switch is turned on. Each job queues into the durable outbox; the emailoutbox
cron does the sending.

Hourly. Each job's id carries its week or its event, so a repeat tick, a
restart or two ticks at once queue nothing extra.
"""
from __future__ import annotations

import asyncio
import random
import traceback
from datetime import datetime, timezone

from database import api_tx
from emails import likes_waiting_weekly
from service.campaigns.runner import audit_send
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

RETURN_MAIL_POLL_SECONDS = env_int('DUO_CRON_RETURN_MAIL_POLL_SECONDS', 60 * 60)

# (name, queue_due). Each runs in its own transaction, so one failing job
# never takes another's queued rows down with it.
JOBS = [
    ('likes_waiting', likes_waiting_weekly.queue_due),
]

print(f'Hello from cron module: {__name__}')


def tick(now: datetime | None = None) -> dict:
    """Run every job once. Returns {name: queued count, or 'error'}. A job
    that queued anything leaves one audit row, as every campaign send does."""
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    for name, job in JOBS:
        try:
            with api_tx() as tx:
                n = job(tx, now)
                if n:
                    audit_send(tx, 'cron', name, dict(queued=n, dry_run=False))
            out[name] = n
        except Exception:
            print(traceback.format_exc())
            out[name] = 'error'
    if any(v for v in out.values()):
        print(f'return_mail: {out}')
    return out


async def return_mail_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(tick))
        await asyncio.sleep(RETURN_MAIL_POLL_SECONDS)
