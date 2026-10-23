"""returnmail - sends the mail held for the owner's proof (health review,
13 Oct 2026, Wave 3): the reasons a member has to come back.

Each job is one module's `queue_due(tx, now)`. A job does nothing while its
switch is off (service/campaigns/switches.py, all off by default) or outside
its own window (service/campaigns/held.py), so this cron runs harmlessly on
every deploy and sends nothing until the owner has confirmed a proof and the
switch is turned on. Each job queues into the durable outbox; the emailoutbox
cron does the sending.

It also runs the quick-question pushes (service/questions/pushes.py) and the
gathering reminder and digest (service/events/jobs.py), each behind its own
switch.

Hourly. Each job's id carries its week or its event, so a repeat tick, a
restart or two ticks at once queue nothing extra.
"""
from __future__ import annotations

import asyncio
import random
import traceback
from datetime import datetime, timezone

from database import api_tx
from emails import likes_waiting_weekly, one_photo_nudge, profile_views_weekly, questions_launch, reminders
from service.questions import pushes as question_pushes
from service.campaigns import held
from service.campaigns.runner import audit_send
from service.events import jobs as event_jobs
from service.matchmaker import introductions as mm_introductions
from service.matchmaker import notices as mm_notices
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

RETURN_MAIL_POLL_SECONDS = env_int('DUO_CRON_RETURN_MAIL_POLL_SECONDS', 60 * 60)

# (name, queue_due). Each runs in its own transaction, so one failing job
# never takes another's queued rows down with it.
JOBS = [
    # Matchmaker (TEC-1845): the alert notices run before the likes email,
    # so an alert email that carried the likes stamps likes_told_at first
    # and that week's likes email skips the member.
    ('mm_member_alerts', mm_notices.queue_member_notices),
    ('mm_visitor_alerts', mm_notices.queue_visitor_notices),
    # Introductions past their date close, silently (5c.4).
    ('mm_intro_close', mm_introductions.close_lapsed),
    ('likes_waiting', likes_waiting_weekly.queue_due),
    ('match_reminder', reminders.queue_match_reminders),
    ('message_reminder', reminders.queue_message_reminders),
    ('profile_views', profile_views_weekly.queue_due),
    ('one_photo', one_photo_nudge.queue_due),
    # Quick questions (TEC-1845). The silent-match push runs before the
    # weekly one: when both are due it wins and spends the week's push.
    ('match_question_push', question_pushes.queue_match_question_pushes),
    # The launch push before the weekly one: in launch week it is the
    # week's question push.
    ('questions_launch_push', question_pushes.queue_launch_pushes),
    ('question_push', question_pushes.queue_weekly_question_pushes),
    # The launch email (TEC-1845): once per member, on a drop day while its
    # switch is on.
    ('questions_launch_email', questions_launch.queue_due),
    # Gatherings (TEC-1845): the reminder the day before and the organiser's
    # daily digest, each behind its email's switch and events_live.
    ('event_reminder', event_jobs.queue_reminders),
    ('event_digest', event_jobs.queue_digests),
    # The one invitation to join, the day after a gathering, to guests who
    # asked for news (TEC-1845), behind its switch and events_live.
    ('event_join_invite', event_jobs.queue_join_invites),
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
        except Exception:
            held.discard_after_commit()
            print(traceback.format_exc())
            out[name] = 'error'
            continue
        out[name] = n
        # After the commit, each push on its own: a push that fails is
        # printed and tried again next tick, and never turns a committed
        # job into an error.
        failed = held.run_after_commit()
        if failed:
            print(f'return_mail: {name}: {failed} push(es) failed, to be tried again next tick')
    if any(v for v in out.values()):
        print(f'return_mail: {out}')
    return out


async def return_mail_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(tick))
        await asyncio.sleep(RETURN_MAIL_POLL_SECONDS)
