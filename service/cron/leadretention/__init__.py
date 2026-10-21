"""Leads are deleted 12 months after their last visit (TEC-1845).

The growth specs promise it: "Rows are deleted 12 months after the last
visit, or on request." A visit is anything that records the lead again or
calls service.leads.touch_lead. An address nobody confirmed goes sooner, a
day after its confirm link lapsed: anyone can type an address into a form,
and anyone retyping it moves last_seen_at, so only created_at counts for
it. Mail queued for a deleted lead goes with it (email_outbox.lead_id
cascades). The feature plans add their own tables' sweeps here (tool
sessions, RSVPs, alerts), on the same clock; gatherings' RSVPs, organiser
links and invite requests are swept here too (service/events/retention.py). Unmatched conversations are
held 30 days for a report, then deleted here (TEC-1845). Daily.
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
    from service.decisions.unmatch import HOLD_DAYS, purge_held_messages
    from service.events.retention import purge_event_data
    from service.matchmaker.retention import purge_matchmaker_data
    from service.tools.retention import purge_stale_tool_sessions
    with api_tx() as tx:
        n = purge_stale_leads(tx)
        n_tools = purge_stale_tool_sessions(tx)
        n_held = purge_held_messages(tx)
        n_events = purge_event_data(tx)
        n_mm = purge_matchmaker_data(tx)
    if n:
        print(f'lead_retention: {n} lead(s) deleted after {RETENTION_DAYS} days without a visit')
    if n_tools:
        print(f'lead_retention: {n_tools} Together session(s) deleted (12 months without a visit, '
              f'30 days unsaved, or 30 days after a delete)')
    if n_held:
        print(f'lead_retention: {n_held} held message(s) of unmatched conversations deleted '
              f'after {HOLD_DAYS} days')
    # Gatherings (TEC-1845).
    if n_events['erased']:
        print(f"lead_retention: {n_events['erased']} RSVP name(s) and email(s) erased "
              f"90 days after their gathering")
    if n_events['digests']:
        print(f"lead_retention: {n_events['digests']} organiser digest(s) naming those guests deleted")
    if n_events['unconfirmed']:
        print(f"lead_retention: {n_events['unconfirmed']} RSVP(s) never confirmed deleted")
    if n_events['links']:
        print(f"lead_retention: {n_events['links']} lapsed organiser link(s) deleted")
    if n_events['requests']:
        print(f"lead_retention: {n_events['requests']} invite request(s) deleted after 12 months")
    # Matchmaker (TEC-1845).
    if n_mm['recommendations_erased']:
        print(f"lead_retention: {n_mm['recommendations_erased']} recommended address(es) and note(s) erased "
              f"7 days after sending")
    if n_mm['recommendations_deleted']:
        print(f"lead_retention: {n_mm['recommendations_deleted']} recommendation(s) deleted after 12 months")
    if n_mm['notes_erased']:
        print(f"lead_retention: {n_mm['notes_erased']} introduction note(s) erased 30 days after closing")
    if n_mm['unconfirmed_alerts']:
        print(f"lead_retention: {n_mm['unconfirmed_alerts']} visitor alert(s) never confirmed deleted")
    if n_mm['mentor_sessions']:
        print(f"lead_retention: {n_mm['mentor_sessions']} lapsed mentor session(s) deleted")
    if n_mm['invitations']:
        print(f"lead_retention: {n_mm['invitations']} mentor invitation(s) never accepted ended")
    if n_mm['mentor_accounts']:
        print(f"lead_retention: {n_mm['mentor_accounts']} mentor account(s) serving nobody for 30 days deleted")


async def lead_retention_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_purge_once))
        await asyncio.sleep(LEAD_RETENTION_POLL_SECONDS)
