"""The unfinished sign-up reminder (TEC-2107; ahavah-web
docs/plans/2026-11-04-unfinished-sign-up-reminder.md, approved 4 Nov 2026).

One email to someone who confirmed their address and started sign-up, then
stopped before an account was made: an `onboardee` row with no `person`
for that address, the people Admin > Users > Unfinished lists
(service/admin/queries/signups.py Q_UNFINISHED, whose rules this reuses).

Due when the last save was more than 24 hours and less than 14 days ago, no
person has the address (in any case), the address never had this reminder,
and it is not on the staff and test list, suppressed or unsubscribed.

Once per address, ever: a claim row in lead_email_send (migration 0063,
campaign `unfinished_signup`) is written in the same transaction as the
outbox row, and its primary key (email, campaign) refuses a second. The
drain marks the claim sent when SMTP accepts the message
(service/campaigns/outbox.py mark_accepted); a claim whose message was
skipped stays unsent and is never tried again.

At most DAILY_CAP queued per Barbados day; the rest wait for the next. Like
the other reminders, nothing is queued on a Friday or Saturday, so nothing
lands on the Sabbath, or before 12:00 UTC. Held: nothing is queued unless
AHAVAH_UNFINISHED_SIGNUP_REMINDER_ENABLED is on.

Logs carry counts only, never a name or an address.

Copy rules: sentence case, no em dashes, no exclamation marks.
"""
from __future__ import annotations

from datetime import datetime

from emails.base import button, callout, chip, is_suppressed_send, render, title_image
from service.admin.queries.signups import REMINDER_CAMPAIGN, STEP_SQL
from service.campaigns import held, outbox
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.leads import address_unsubscribed, clean_email
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = REMINDER_CAMPAIGN
CAMPAIGN_ID = 'once'
SWITCH = 'unfinished_signup_reminder'
UNSUB_SCOPE = 'signup'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
TARGET = f"{WEB_BASE_URL}/"
DAILY_CAP = 20

SUBJECT = "Your Ahavah sign-up is waiting"
PREHEADER = "A few steps left, then the community can see you."
CHIP = "Almost there"
# The body, one entry per paragraph. A second paragraph goes here and
# nowhere else ("Your answers so far are saved." waits on a separate check).
PARAGRAPHS = (
    "You started joining Ahavah and stopped before the end. It takes a few minutes to finish, "
    "and then the community can see your profile.",
)
BUTTON = "Finish signing up"
CALLOUT = "It takes about 2 minutes."
FOOTER_REASON = "You're receiving this because you started signing up for Ahavah."

_Q_DUE = f"""
    WITH o AS (
        SELECT lower(o.email) AS email, o.updated_at, o.lead_source, {STEP_SQL} AS furthest_step
          FROM onboardee o
         WHERE o.updated_at < %(now)s::timestamptz - INTERVAL '24 hours'
           AND o.updated_at > %(now)s::timestamptz - INTERVAL '14 days'
           AND NOT EXISTS (SELECT 1 FROM person p WHERE lower(p.email) = lower(o.email))
           AND lower(o.email) <> ALL(%(ex)s)
           AND NOT EXISTS (SELECT 1 FROM lead_email_send s
                            WHERE s.email = lower(o.email) AND s.campaign = %(c)s)
    )
    SELECT email FROM o
     WHERE lead_source IS NULL OR furthest_step <> 'none'
     ORDER BY updated_at, email
"""

_Q_QUEUED_TODAY = """
    SELECT count(*) AS n FROM lead_email_send
     WHERE campaign = %(c)s
       AND (claimed_at AT TIME ZONE 'America/Barbados')::date
           = (%(now)s::timestamptz AT TIME ZONE 'America/Barbados')::date
"""

_Q_CLAIM = """
    INSERT INTO lead_email_send (email, campaign, claimed_at)
    VALUES (%(e)s, %(c)s, %(now)s)
    ON CONFLICT (email, campaign) DO NOTHING
    RETURNING email
"""

# One tick at a time. A second tick that finds the lock taken queues
# nothing; the next hourly tick picks up whoever is still due. The claim's
# primary key stops a second email to one address whatever happens here;
# the lock is what keeps 2 ticks at once inside the daily cap.
_Q_LOCK = "SELECT pg_try_advisory_xact_lock(hashtext('returnmail:unfinished_signup')) AS ok"


def unfinished_signup_html(cta_url: str, unsubscribe_url: str) -> str:
    paras = [held.para(text, bottom=24 if i == len(PARAGRAPHS) - 1 else 18)
             for i, text in enumerate(PARAGRAPHS)]
    body = f"""
{chip(CHIP)}

{title_image("title-finish-profile.png", "title-finish-profile-wht.png", "Finish your profile.", 447)}

{''.join(paras)}

{button(BUTTON, cta_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout(CALLOUT)}
"""
    return render(title=SUBJECT, preheader=PREHEADER, body_html=body,
                  footer_html=held.footer(FOOTER_REASON, unsubscribe_url))


def _normalized(email: str):
    cleaned = clean_email(email)
    return cleaned[1] if cleaned else None


def queue_due(tx, now: datetime) -> int:
    """Queue the reminder for everyone due, up to the day's cap. Returns how
    many were queued."""
    if not enabled(SWITCH) or not held.in_reminder_window(now):
        return 0
    if not tx.execute(_Q_LOCK).fetchone()['ok']:
        print('unfinished_signup: another tick is running; nothing queued')
        return 0
    room = DAILY_CAP - int(tx.execute(_Q_QUEUED_TODAY, dict(c=CAMPAIGN, now=now)).fetchone()['n'])
    due = [r['email'] for r in tx.execute(_Q_DUE, dict(now=now, ex=_excluded(), c=CAMPAIGN)).fetchall()]
    queued = refused = 0
    for email in due:
        if queued >= room:
            break
        if is_suppressed_send(email) or address_unsubscribed(tx, _normalized(email)):
            refused += 1
            continue
        if tx.execute(_Q_CLAIM, dict(e=email, c=CAMPAIGN, now=now)).fetchone() is None:
            continue
        unsub = unsub_url(UNSUB_SCOPE, email, WEB_BASE_URL)
        if outbox.enqueue_for_onboardee(
                tx, campaign=CAMPAIGN, campaign_id=CAMPAIGN_ID, email=email, subject=SUBJECT,
                html=unfinished_signup_html(TARGET, unsub), from_addr=FROM_ADDR,
                list_unsubscribe=held.list_unsubscribe(unsub), switch=SWITCH) is not None:
            queued += 1
    if due:
        waiting = len(due) - queued - refused
        print(f'unfinished_signup: {len(due)} due, {queued} queued, {refused} suppressed or '
              f'unsubscribed, {max(waiting, 0)} waiting (cap {DAILY_CAP} a day, '
              f'{max(room - queued, 0)} left today)')
    return queued


def preview(to: str) -> tuple[str, str]:
    """The proof. Nothing stored."""
    return SUBJECT, unfinished_signup_html(TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
