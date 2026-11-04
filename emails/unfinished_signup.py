"""The unfinished sign-up reminder (TEC-2107; ahavah-web
docs/plans/2026-11-04-unfinished-sign-up-reminder.md, approved 4 Nov 2026).

One email to someone who confirmed their address and started sign-up, then
stopped before an account was made: an `onboardee` row with no `person`
for that address, the people Admin > Users > Unfinished lists
(service/admin/queries/signups.py Q_UNFINISHED, whose rules this reuses).

Due when the last save was more than 24 hours and less than 14 days ago, no
person has the address (in any case), the address never had this reminder,
and it is not on the staff and test list, suppressed or unsubscribed from
any mail an address with no account can leave
(service/campaigns/outbox.py onboardee_unsubscribed). The garbage cron
deletes an onboardee a week after its last save, so in practice the window
is 24 hours to 7 days; the 14-day bound stays in case that changes.

Once per address, ever: a claim row in lead_email_send (migration 0063,
campaign `unfinished_signup`) is written in the same transaction as the
outbox row, and its primary key (email, campaign) refuses a second. Its
email column holds a keyed hash of the address
(service.admin.queries.signups.claim_key), never the address, since it
outlives the onboardee. The drain marks the claim sent when SMTP accepts
the message (service/campaigns/outbox.py mark_accepted); a claim whose
message was skipped stays unsent and is never tried again. The outbox row,
which holds the address, is deleted 30 days after it settles (the
lead_retention cron).

At most DAILY_CAP queued per Barbados day; the rest wait for the next. Like
the other reminders, nothing is queued on a Friday or Saturday, so nothing
lands on the Sabbath, or before 12:00 UTC. Held: nothing is queued unless
AHAVAH_UNFINISHED_SIGNUP_REMINDER_ENABLED is on.

Logs carry counts only, never a name or an address. While the switch is
off each tick logs `unfinished_signup: switch off`.

Copy rules: sentence case, no em dashes, no exclamation marks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from emails.base import button, callout, chip, is_suppressed_send, render, title_image
from service.admin.queries.signups import REMINDER_CAMPAIGN, STEP_SQL, claim_key
from service.campaigns import held, outbox
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = REMINDER_CAMPAIGN
CAMPAIGN_ID = 'once'
SWITCH = 'unfinished_signup_reminder'
UNSUB_SCOPE = 'signup'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
TARGET = f"{WEB_BASE_URL}/"
DAILY_CAP = 20
# The due window. The garbage cron deletes an onboardee 7 days after its
# last save, so the 14-day bound is not reached today.
DUE_AFTER = timedelta(hours=24)
DUE_BEFORE = timedelta(days=14)

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
         WHERE o.updated_at < %(after)s AND o.updated_at > %(before)s
           AND NOT EXISTS (SELECT 1 FROM person p WHERE lower(p.email) = lower(o.email))
           AND lower(o.email) <> ALL(%(ex)s)
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

# The claims among these keys: the due query cannot join on a keyed hash.
_Q_CLAIMS = """
    SELECT email, sent_at FROM lead_email_send WHERE campaign = %(c)s AND email = ANY(%(k)s)
"""

_Q_PENDING = """
    SELECT onboardee_email FROM email_outbox
     WHERE campaign = %(c)s AND onboardee_email = ANY(%(e)s) AND state IN ('queued', 'reserved')
"""

_Q_CLAIM = """
    INSERT INTO lead_email_send (email, campaign, claimed_at)
    VALUES (%(k)s, %(c)s, %(now)s)
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


def queue_due(tx, now: datetime) -> int:
    """Queue the reminder for everyone due, up to the day's cap. Returns how
    many were queued."""
    if not enabled(SWITCH):
        print('unfinished_signup: switch off')
        return 0
    if not held.in_reminder_window(now):
        return 0
    if not tx.execute(_Q_LOCK).fetchone()['ok']:
        print('unfinished_signup: another tick is running; nothing queued')
        return 0
    room = DAILY_CAP - int(tx.execute(_Q_QUEUED_TODAY, dict(c=CAMPAIGN, now=now)).fetchone()['n'])
    found = [r['email'] for r in tx.execute(_Q_DUE, dict(
        after=now - DUE_AFTER, before=now - DUE_BEFORE, ex=_excluded())).fetchall()]
    keys = {e: claim_key(e) for e in found}
    claimed = {r['email'] for r in tx.execute(
        _Q_CLAIMS, dict(c=CAMPAIGN, k=list(keys.values()))).fetchall()}
    due = [e for e in found if keys[e] not in claimed]
    queued = refused = 0
    for email in due:
        if queued >= room:
            break
        if is_suppressed_send(email) or outbox.onboardee_unsubscribed(tx, email):
            refused += 1
            continue
        if tx.execute(_Q_CLAIM, dict(k=keys[email], c=CAMPAIGN, now=now)).fetchone() is None:
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


def reminder_states(tx, rows: list[dict], now: Optional[datetime] = None) -> list[tuple]:
    """(reminder_state, reminded_at) for each of the Unfinished list's rows
    (each with `email` and `last_saved_at`), for Admin > Users > Unfinished.

      None        the switch is off, or the last save is under 24 hours old
      'sent'      accepted for sending; reminded_at says when
      'due'       not reminded yet and inside the window, or queued
      'not_sent'  claimed but skipped or failed, refused (suppressed or
                  unsubscribed), or past the window without one

    reminded_at is the send date whichever way the switch is set."""
    if not rows:
        return []
    now = now or datetime.now(timezone.utc)
    on = enabled(SWITCH)
    keys = [claim_key(r['email']) for r in rows]
    claims = {c['email']: c['sent_at'] for c in tx.execute(
        _Q_CLAIMS, dict(c=CAMPAIGN, k=keys)).fetchall()}
    pending = {r['onboardee_email'] for r in tx.execute(
        _Q_PENDING, dict(c=CAMPAIGN, e=[r['email'] for r in rows])).fetchall()}
    out = []
    for r, key in zip(rows, keys):
        sent_at = claims.get(key)
        if not on:
            state = None
        elif sent_at is not None:
            state = 'sent'
        elif key in claims:
            state = 'due' if r['email'] in pending else 'not_sent'
        elif r['last_saved_at'] > now - DUE_AFTER:
            state = None
        elif (r['last_saved_at'] <= now - DUE_BEFORE or is_suppressed_send(r['email'])
              or outbox.onboardee_unsubscribed(tx, r['email'])):
            state = 'not_sent'
        else:
            state = 'due'
        out.append((state, sent_at))
    return out


def preview(to: str) -> tuple[str, str]:
    """The proof. Nothing stored."""
    return SUBJECT, unfinished_signup_html(TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
