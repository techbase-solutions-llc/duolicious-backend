"""Dormancy: hides a profile after 30 days offline.

Owner decision 1 Oct 2026 (TEC-1607): inactive profiles stay visible on the
map and in the feed, so production runs this in DRY RUN and the members it
had hidden were brought back (scripts/reactivate_dormant.py). The module
stays so the decision can be reversed with one env var.

Before reversing it, know what a real run does (sql/__init__.py): it hides
the member, takes them out of their club count, DELETES EVERY SESSION they
hold and emails "Your Ahavah profile is resting". Only a new email code
brings the profile back (check-otp sets activated), so each member it
catches is signed out on every device (reported 16 Nov 2026, TEC-1832).
"""
from database.asyncdatabase import api_tx
from service.cron.autodeactivate2.sql import *
from service.cron.autodeactivate2.template import emailtemplate
from service.cron.cronutil import env_int, print_stacktrace, MAX_RANDOM_START_DELAY
from smtp import aws_smtp
from smtp.guard import dry_run
import asyncio
import os
import random

DRY_RUN = os.environ.get(
    'DUO_CRON_AUTODEACTIVATE2_DRY_RUN',
    'true',
).lower() not in ['false', 'f', '0', 'no']

AUTODEACTIVATE2_POLL_SECONDS = env_int(
    'DUO_CRON_AUTODEACTIVATE2_POLL_SECONDS',
    60 * 10, # 10 minutes
)

print(f'Hello from cron module: {__name__}')

def maybe_send_email(email: str):
    if email.lower().endswith('@example.com'):
        return

    send_args = dict(
        subject="Your Ahavah profile is resting",
        body=emailtemplate(),
        to_addr=email,
        kind='profile_resting',
    )

    from emails.base import mask_email
    print('autodeactivate2: sending deactivation email to', mask_email(email))
    aws_smtp.send(**send_args)

async def autodeactivate2_once():
    # The send guard's tripwire (2 Nov 2026): in a dry run any send raises
    # and alerts the owner, whatever the code below does.
    with dry_run(DRY_RUN):
        await _autodeactivate2_once()

async def _autodeactivate2_once():
    params = dict(
        dry_run=DRY_RUN,
    )

    async with api_tx() as tx:
        cur_deactivated = await tx.execute(Q_DEACTIVATE, params)
        rows_deactivated = await cur_deactivated.fetchall()

    # Ids only, never the address: a dry run logs the same members on every
    # tick, and it wrote each one's email to the cron log every 5 minutes
    # (1,436 lines in 48 hours on 23 Nov 2026).
    if DRY_RUN and rows_deactivated:
        print(
            f'  - autodeactive2: DUO_CRON_AUTODEACTIVATE2_DRY_RUN env var '
            f'prevented deactivation of {len(rows_deactivated)} member(s): '
            f'ids {[p["id"] for p in rows_deactivated]}'
        )
    elif not DRY_RUN:
        for p in rows_deactivated:
            print(f'  - autodeactive2: deactivated id {p["id"]}')

    # A dry run hides nobody, so it must email nobody. It used to email the same
    # members "Your Ahavah profile is resting" every 10 minutes (owner, 2 Nov 2026).
    if DRY_RUN:
        return

    for p in rows_deactivated:
        maybe_send_email(p['email'])

async def autodeactivate2_forever():
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(autodeactivate2_once)
        await asyncio.sleep(AUTODEACTIVATE2_POLL_SECONDS)
