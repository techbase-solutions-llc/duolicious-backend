"""Leads are deleted 12 months after their last visit (TEC-1845).

The growth specs promise it: "Rows are deleted 12 months after the last
visit, or on request." A visit is anything that records the lead again or
calls service.leads.touch_lead. An address nobody confirmed goes sooner, a
day after its confirm link lapsed: anyone can type an address into a form,
and anyone retyping it moves last_seen_at, so only created_at counts for
it. Mail queued for a deleted lead goes with it (email_outbox.lead_id
cascades). The feature plans add their own tables' sweeps here (tool
sessions, RSVPs, alerts), on the same clock. Daily.
"""
from __future__ import annotations

import asyncio
import random

from database import api_tx
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.leads import CONFIRM_TTL, RETENTION_DAYS

LEAD_RETENTION_POLL_SECONDS = env_int('DUO_CRON_LEAD_RETENTION_POLL_SECONDS', 60 * 60 * 24)

print(f'Hello from cron module: {__name__}')

_Q_PURGE = """
    DELETE FROM lead
     WHERE last_seen_at < NOW() - make_interval(days => %(days)s)
        OR (confirmed_at IS NULL AND created_at < NOW() - %(ttl)s - interval '1 day')
"""


def purge_stale_leads(tx) -> int:
    return tx.execute(_Q_PURGE, dict(days=RETENTION_DAYS, ttl=CONFIRM_TTL)).rowcount


def _purge_once() -> None:
    with api_tx() as tx:
        n = purge_stale_leads(tx)
    if n:
        print(f'lead_retention: {n} lead(s) deleted after {RETENTION_DAYS} days without a visit')


async def lead_retention_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_purge_once))
        await asyncio.sleep(LEAD_RETENTION_POLL_SECONDS)
