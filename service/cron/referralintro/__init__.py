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

Until 13 Oct 2026 the template was the beta cohort's body with the member
footer, which told members they had opted into a beta (health review,
finding 68). Members now get their own body (emails/referral_intro.py
`_member_body`), and nothing is queued until the owner has confirmed its
proof and AHAVAH_REFERRAL_MEMBER_BODY_ENABLED is on.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.referral_intro import FROM_ADDR, MEMBER_SUBJECT, referral_intro_html
from service.campaigns import (make_campaign_link, outbox, suppressed_predicate_sql,
                               unsubscribed_predicate_sql)
from service.campaigns.runner import audit_send
from service.campaigns.switches import enabled
from service.config import WEB_BASE_URL
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

UNSUB_SCOPE = 'campaigns'
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


_Q_ALREADY_QUEUED = """
    SELECT 1 FROM email_outbox
     WHERE campaign = 'referral' AND campaign_id = %(cid)s AND person_id = %(p)s
"""


def _week_suffix(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}w{week:02d}"


def campaign_id(person_id: int, now: datetime) -> str:
    return f"referral-{person_id}-{_week_suffix(now)}"


def queue_due(tx, now: datetime | None = None, *, cap_days: int = 7,
              not_before: datetime | None = None, id_suffix: str | None = None,
              actor: str = 'cron') -> int:
    """Queue the intro for every member due one. Returns how many rows were
    queued this tick (not how many were due: the outbox dedupes repeats).

    The keyword arguments exist for a deliberate one-off run from the
    command line (scripts/schedule_referral_intro.py): `not_before` holds the
    rows for a chosen slot, `cap_days` is the frequency window the drain
    re-checks at that slot, and `id_suffix` replaces the ISO week in the id
    so the run cannot collide with the cron's own row for the week.

    A tick that queues anything leaves one audit row in the same
    transaction, under `actor` ('cron', or 'cli' from the script). Each
    member's campaign id is their own, so the row names the shared suffix
    rather than one id."""
    # The members' own body waits for the owner's proof (finding 68): until
    # AHAVAH_REFERRAL_MEMBER_BODY_ENABLED is on, nothing is queued, so the
    # beta body no longer reaches members who never joined a beta.
    if not enabled('referral_member'):
        return 0
    now = now or datetime.now(timezone.utc)
    rows = tx.execute(_Q_DUE, dict(days=REFERRAL_INTRO_AFTER_DAYS, ex=_excluded(),
                                   sup=suppressed_sql_pattern())).fetchall()
    queued = 0
    for r in rows:
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        cid = f"referral-{r['id']}-{id_suffix}" if id_suffix else campaign_id(r['id'], now)
        # Already queued under this id (an earlier tick this week): the
        # outbox would add nothing, so mint no links for it either.
        if tx.execute(_Q_ALREADY_QUEUED, dict(cid=cid, p=r['id'])).fetchone():
            continue
        # Counted links (finding 74): kind 'referral', the member as subject,
        # as E2, E3 and E6 carry theirs.
        code = r['referral_code']
        share_href = make_campaign_link(tx, 'referral', f"{WEB_BASE_URL}/share/{code}", r['id'])
        link_href = make_campaign_link(tx, 'referral', f"{WEB_BASE_URL}/i/{code}", r['id'])
        row_id = outbox.enqueue(
            tx, campaign='referral', campaign_id=cid, person_id=r['id'],
            email=r['email'], subject=MEMBER_SUBJECT,
            html=referral_intro_html(r['email'], code, member=True,
                                     share_href=share_href, link_href=link_href),
            from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE,
            list_unsubscribe=f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{unsub}>",
            cap_days=cap_days, not_before=not_before)
        if row_id is not None:
            queued += 1
    if queued:
        audit_send(tx, actor, 'referral', dict(
            queued=queued, dry_run=False, id_suffix=id_suffix or _week_suffix(now),
            cap_days=cap_days, not_before=not_before.isoformat() if not_before else None))
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
