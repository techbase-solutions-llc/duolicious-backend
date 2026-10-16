"""The weekly "Question of the week" post (TEC-1845).

Queues next week's prompt post once a day; the request key is the ISO week,
so every run after the first that week changes nothing. The post waits for
its artwork and the owner's approval like every other. Off unless
DUO_CRON_QUESTION_OF_WEEK_ENABLED is set to 1, true, yes or on: the owner
confirms the caption and the bank's wording first.
"""
from __future__ import annotations

import asyncio
import os
import random

from database import api_tx
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.spotlight.growthposts import queue_question_of_week

ENABLED = os.environ.get('DUO_CRON_QUESTION_OF_WEEK_ENABLED', '').strip().lower() in (
    '1', 'true', 'yes', 'on')
POLL_SECONDS = env_int('DUO_CRON_QUESTION_OF_WEEK_POLL_SECONDS', 60 * 60 * 24)

print(f'Hello from cron module: {__name__}')


def _queue_once() -> None:
    with api_tx() as tx:
        rk = queue_question_of_week(tx)
    print(f'question_of_week: {rk or "nothing queued (empty bank or no free day)"}')


async def question_of_week_forever() -> None:
    if not ENABLED:
        print('question_of_week: disabled, set DUO_CRON_QUESTION_OF_WEEK_ENABLED=1')
        return
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_queue_once))
        await asyncio.sleep(POLL_SECONDS)
