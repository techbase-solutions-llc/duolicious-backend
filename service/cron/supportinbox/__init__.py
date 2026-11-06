"""The copy of support@ahavah.app in the admin (TEC-2115).

Every 5 minutes, service.support_inbox.tick reads the mail a Gmail filter
forwards from support@ahavah.app to a Resend receiving address, through
Resend's received-mail API, read only, and stores each new message. Off
unless AHAVAH_SUPPORT_INBOX_ENABLED is on: while it is off a pass does
nothing and prints nothing. With it on but no AHAVAH_SUPPORT_INBOUND_ADDRESS
or no Resend key, it says so once and checks nothing. It sends nothing.
Copies are deleted a year after they arrived, by the lead_retention cron.

`tick` is sync (blocking HTTPS and short transactions), so it runs on a
thread here, as the send guard's tick does.
"""
from __future__ import annotations

import asyncio
import random

from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

SUPPORT_INBOX_POLL_SECONDS = env_int('DUO_CRON_SUPPORT_INBOX_POLL_SECONDS', 60 * 5)

print(f'Hello from cron module: {__name__}')


def _tick() -> None:
    from service import support_inbox
    support_inbox.tick()


async def support_inbox_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_tick))
        await asyncio.sleep(SUPPORT_INBOX_POLL_SECONDS)
