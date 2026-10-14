"""Shared pieces of the mail held for the owner's proof (health review,
13 Oct 2026, Wave 3): when each weekly job may run, the gap between nudges,
the footer, and the one way each message is queued.

Every message goes through the durable outbox (service/campaigns/outbox.py)
under its own campaign name, so the drain re-checks suppression, the
member's unsubscribe scope and the per-run id at send time, and writes the
send log on acceptance.

THE CAPS. These campaigns are listed in SELF_CAPPED_CAMPAIGNS
(service/campaigns/__init__.py) and queued `exempt`: the 7 day cross-campaign
cap would meet the weekly E2 and skip nearly everyone. Each keeps its own
cadence instead, written into its recipient query:

  likes_waiting, one_photo, profile_views   once per ISO week at most (the
      weekly id), plus their own longer rule where one is stated, and never
      within NUDGE_GAP_DAYS of another of these three or a reminder
  match_reminder, message_reminder          once per stage (3 days, then 10)
      of one match or one unread conversation
  friend_joined                             once per friend who joins

Weekly jobs run on their own weekday from 12:00 UTC (08:00 Barbados), never
on Friday or Saturday, so nothing lands on the Sabbath.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from typing import Optional

from emails.base import MUTED, INK_SOFT, SANS
from service.campaigns import outbox

NUDGE_GAP_DAYS = 3

# The campaigns that count for the gap.
_GAP_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                  'match_reminder', 'message_reminder')

SEND_HOUR_UTC = 12

# ISO weekday of each weekly job. Monday is E2's.
WEEKDAY = {'one_photo': 2, 'profile_views': 3, 'likes_waiting': 4}

# Reminders run any day but Friday and Saturday.
REMINDER_DAYS = (7, 1, 2, 3, 4)


def nudged_recently_sql(person_ref: str) -> str:
    """SQL boolean: this member was queued one of the gap campaigns in the
    last NUDGE_GAP_DAYS. Read from the outbox, not the send log, so two jobs
    in the same tick see each other's rows before the drain has run. A
    message the drain skipped does not count."""
    names = ', '.join(f"'{c}'" for c in _GAP_CAMPAIGNS)
    return f"""EXISTS (SELECT 1 FROM email_outbox o
                WHERE o.person_id = {person_ref} AND o.campaign IN ({names})
                  AND o.state IN ('queued', 'reserved', 'accepted', 'acceptance_unknown')
                  AND o.created_at > NOW() - make_interval(days => {NUDGE_GAP_DAYS}))"""


def in_weekly_window(now: datetime, campaign: str) -> bool:
    return now.isoweekday() == WEEKDAY[campaign] and now.hour >= SEND_HOUR_UTC


def in_reminder_window(now: datetime) -> bool:
    return now.isoweekday() in REMINDER_DAYS and now.hour >= SEND_HOUR_UTC


def week_suffix(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}w{week:02d}"


def para(text: str, *, size: int = 17, bottom: int = 18, muted: bool = False) -> str:
    color = MUTED if muted else INK_SOFT
    return (f'<p class="e-text" style="margin:0 0 {bottom}px;font-family:{SANS};'
            f'font-size:{size}px;line-height:1.55;color:{color};">{text}</p>')


def footer(reason: str, unsubscribe_url: str, label: str = 'Unsubscribe') -> str:
    return f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
{reason}
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">{label}</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
</div>
"""


def list_unsubscribe(unsub_url: str) -> str:
    return f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{unsub_url}>"


def queue(tx, *, campaign: str, campaign_id: str, person_id: int, email: str,
          subject: str, html: str, from_addr: Optional[str], unsub_scope: str,
          unsub_url: str) -> Optional[int]:
    """Queue one held message: exempt from the cross-campaign cap (see the
    module docstring), deduped on (campaign, campaign_id, person_id)."""
    return outbox.enqueue(
        tx, campaign=campaign, campaign_id=campaign_id, person_id=person_id,
        email=email, subject=subject, html=html, from_addr=from_addr,
        unsub_scope=unsub_scope, list_unsubscribe=list_unsubscribe(unsub_url),
        exempt=True)


# Work that must wait until the job's transaction has committed: a push.
# service.notifications.send_to_user_safe re-reads the member's preferences
# in a transaction of its own, which must never open inside the job's (api_tx
# is never nested), and a push for a decision that then rolled back would be
# a push nobody recorded. The returnmail cron runs these after each job
# commits, and drops them when a job fails.
#
# Each runs on its own (review of Wave 3, 14 Oct 2026): one that raises is
# printed and its `on_failure` runs, and the rest still go. Until then one
# push raising lost every push after it in that job, each already logged
# in push_send_log and so never tried again, and the tick reported an error
# for a job whose transaction had committed.
_AFTER_COMMIT: list = []


def after_commit(fn, on_failure=None) -> None:
    """`on_failure` runs, in no transaction, when `fn` raises: the reminders
    use it to take back the push_send_log row, so the push is tried again
    next tick rather than counted as sent."""
    _AFTER_COMMIT.append((fn, on_failure))


def run_after_commit() -> int:
    """Run every pending callback. Returns how many raised; never raises."""
    pending = list(_AFTER_COMMIT)
    _AFTER_COMMIT.clear()
    failed = 0
    for fn, on_failure in pending:
        try:
            fn()
        except Exception:
            failed += 1
            print(traceback.format_exc())
            if on_failure is not None:
                try:
                    on_failure()
                except Exception:
                    print(traceback.format_exc())
    return failed


def discard_after_commit() -> None:
    _AFTER_COMMIT.clear()


def already_queued(tx, campaign: str, campaign_id: str, person_id: int) -> bool:
    """True when this exact message is already in the outbox, so a repeat
    tick mints no links for a message the outbox would refuse anyway."""
    return tx.execute(
        """SELECT 1 FROM email_outbox
            WHERE campaign = %(c)s AND campaign_id = %(cid)s AND person_id = %(p)s""",
        dict(c=campaign, cid=campaign_id, p=person_id)).fetchone() is not None
