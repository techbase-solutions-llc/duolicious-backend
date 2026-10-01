"""referralintro - sends every member their invite link a week after joining.

Until 1 Oct 2026 the referral intro ("Your link to bring someone in") was a
beta-era blast run by hand from emails/send_referral_intro.py and keyed on
beta_signup. 32 of the 54 members joined after the beta and never had it.

THE SEND LOG IS THE GUARD, NOT THE CLOCK.

Every tick queues the intro for each activated member who joined more than
REFERRAL_INTRO_AFTER_DAYS ago, has a referral code, is not staff, never had
the beta intro, and has no `referral` row in email_send_log. The outbox
dedupes on (campaign, campaign_id, person_id), and the id carries the ISO
week, so:

  * a second tick in the same week queues nothing extra,
  * a message the drain SKIPPED under the 7 day frequency cap (the member
    got another email this week) is tried again next week under a new id,
  * once the drain ACCEPTS one, the send log row stops every future tick.

The template is the same one the beta cohort had, with the member footer:
these members did not opt into a beta, they joined Ahavah.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.referral_intro import FROM_ADDR, SUBJECT, referral_intro_html
from service.campaigns import outbox, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.config import WEB_BASE_URL
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

UNSUB_SCOPE = 'notifications'
REFERRAL_INTRO_AFTER_DAYS = 7

REFERRAL_INTRO_ENABLED = env_int('DUO_CRON_REFERRAL_INTRO_ENABLED', 1) == 1
REFERRAL_INTRO_POLL_SECONDS = env_int('DUO_CRON_REFERRAL_INTRO_POLL_SECONDS', 60 * 60 * 24)

print(f'Hello from cron module: {__name__}')

_Q_DUE = f"""
    SELECT p.id, p.email, p.referral_code
      FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND p.referral_code IS NOT NULL
       AND p.sign_up_time < NOW() - make_interval(days => %(days)s)
       AND 'admin' <> ALL(COALESCE(p.roles, ARRAY[]::text[]))
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT EXISTS (SELECT 1 FROM beta_signup b
                        WHERE lower(b.email) = lower(p.email)
                          AND b.referral_intro_sent_at IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = 'referral')
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
     ORDER BY p.id
"""


def campaign_id(person_id: int, now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"referral-{person_id}-{year}w{week:02d}"


def queue_due(tx, now: datetime | None = None) -> int:
    """Queue the intro for every member due one. Returns how many rows were
    queued this tick (not how many were due: the outbox dedupes repeats)."""
    now = now or datetime.now(timezone.utc)
    rows = tx.execute(_Q_DUE, dict(days=REFERRAL_INTRO_AFTER_DAYS, ex=_excluded(),
                                   sup=suppressed_sql_pattern())).fetchall()
    queued = 0
    for r in rows:
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        row_id = outbox.enqueue(
            tx, campaign='referral', campaign_id=campaign_id(r['id'], now), person_id=r['id'],
            email=r['email'], subject=SUBJECT,
            html=referral_intro_html(r['email'], r['referral_code'], member=True),
            from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE,
            list_unsubscribe=f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{unsub}>",
            cap_days=7)
        if row_id is not None:
            queued += 1
    return queued


def _tick() -> None:
    with api_tx() as tx:
        n = queue_due(tx)
    # Zero is the normal case on every tick after the first: say something
    # only when something happened.
    if n:
        print(f'referral_intro: queued {n}')


async def referral_intro_forever() -> None:
    if not REFERRAL_INTRO_ENABLED:
        print('referral_intro: disabled, set DUO_CRON_REFERRAL_INTRO_ENABLED=1')
        return
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_tick))
        await asyncio.sleep(REFERRAL_INTRO_POLL_SECONDS)
