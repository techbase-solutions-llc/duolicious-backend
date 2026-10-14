"""Match and message reminders (health review, 13 Oct 2026, finding 61).

Matches stall with nobody reminded: the match notification goes once, at
creation, and the message notification once per unread state and only for
the last 10 days. These remind at two stages, 3 days and then 10 days:

  match_reminder    a match where neither side has written: each side is
                    reminded, so long as they were not online in the last day.
  message_reminder  a member with unread messages they have not been online
                    since: one reminder covering every unread conversation,
                    keyed on the newest, so a new message starts a new cycle.

Nobody is named (whether a reminder may name the match is the owner's open
decision on finding 61): no name, no photo, nothing from the messages.
Reading a conversation clears it; writing a first message ends a match's
reminders.

Push first, as notify() does: a member with push on for that event
(push_matches, push_messages) and a live subscription gets a push, logged
in push_send_log (migration 0064) so it goes once. Otherwise email, if the
member has that email on (email_matches, email_messages), through the
outbox with the `notifications` unsubscribe scope.

Held: nothing goes unless AHAVAH_MATCH_REMINDER_ENABLED or
AHAVAH_MESSAGE_REMINDER_ENABLED is on (service/campaigns/switches.py).
Sunday to Thursday from 12:00 UTC, never on the Sabbath.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime

from emails.base import button, chip, render, suppressed_sql_pattern, title_image
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns import held
from service.campaigns.switches import enabled
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

MATCH = 'match_reminder'
MESSAGE = 'message_reminder'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = None   # the mailer's default, as the match and message emails use

# (stage, from days, to days)
STAGES = (('d3', 3, 10), ('d10', 10, 60))

MATCH_PUSH = dict(title='Say hello to your match',
                  body='Neither of you has written yet. A short hello is enough.',
                  url='/matches', kind='match')
MESSAGE_PUSH = dict(title='A message is waiting for you',
                    body='Someone is waiting for your reply on Ahavah.',
                    url='/inbox', kind='message')
# What scripts/send_proofs.py pushes to the owner's account.
PUSH_PROOFS = [MATCH_PUSH, MESSAGE_PUSH]


def _pref(column: str) -> str:
    return (f"COALESCE((SELECT np.{column} FROM notification_preference np "
            f"WHERE np.person_id = p.id), TRUE)")


def _common(alias: str = 'p') -> str:
    return f"""{alias}.activated AND {alias}.deletion_requested_at IS NULL
       AND lower({alias}.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, f'{alias}.id')})
       AND NOT ({suppressed_predicate_sql(f'{alias}.email')})"""


_Q_MATCHES = f"""
    WITH m AS (
        SELECT match_id, user_a_id, user_b_id,
               floor(extract(epoch FROM NOW() - created_at) / 86400)::int AS days
          FROM ahavah_match
         WHERE created_at < NOW() - make_interval(days => 3)
           AND created_at > NOW() - make_interval(days => 60)
           AND NOT EXISTS (SELECT 1 FROM messaged x
                            WHERE (x.subject_person_id = user_a_id AND x.object_person_id = user_b_id)
                               OR (x.subject_person_id = user_b_id AND x.object_person_id = user_a_id))
           AND NOT is_blocked_pair(user_a_id, user_b_id)
    ), sides AS (
        SELECT match_id, days, user_a_id AS pid, user_b_id AS other FROM m
        UNION ALL
        SELECT match_id, days, user_b_id, user_a_id FROM m
    )
    SELECT s.match_id::text AS match_id, s.days, p.id AS person_id, p.email,
           {_pref('push_matches')} AS push_on, {_pref('email_matches')} AS email_on,
           EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id) AS has_push
      FROM sides s
      JOIN person p ON p.id = s.pid
      JOIN person o ON o.id = s.other AND o.activated
     WHERE {_common()}
       AND (p.last_online_time IS NULL OR p.last_online_time < NOW() - interval '1 day')
     ORDER BY p.id
"""

# Unread conversations, by the inbox's own counters (never the messages).
# The sender must still be activated and not blocked.
_Q_MESSAGES = f"""
    WITH unread AS (
        SELECT p.id AS pid, count(*) AS people, max(i.timestamp) AS newest_us
          FROM inbox i
          JOIN person p ON p.uuid = uuid_or_null(i.luser)
          JOIN person s ON s.uuid = uuid_or_null(split_part(i.remote_bare_jid, '@', 1))
         WHERE i.unread_count > 0
           AND s.activated
           AND NOT is_blocked_pair(p.id, s.id)
         GROUP BY p.id
    )
    SELECT p.id AS person_id, p.email, u.people,
           (u.newest_us / 1000000)::bigint AS newest_s,
           floor((extract(epoch FROM NOW()) - u.newest_us / 1000000.0) / 86400)::int AS days,
           {_pref('push_messages')} AS push_on, {_pref('email_messages')} AS email_on,
           EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id) AS has_push
      FROM unread u
      JOIN person p ON p.id = u.pid
     WHERE {_common()}
       AND (p.last_online_time IS NULL
            OR extract(epoch FROM p.last_online_time) < u.newest_us / 1000000.0)
     ORDER BY p.id
"""


def _stage(days: int):
    for name, lo, hi in STAGES:
        if lo <= days < hi:
            return name
    return None


def PUSH_READY() -> bool:
    from service.notifications import PUSH_ENABLED
    return PUSH_ENABLED


def _push(person_id: int, title: str, body: str, url: str, kind: str) -> None:
    from service.notifications import send_to_user_safe
    send_to_user_safe(person_id, title, body, url, event_kind=kind)


def _already(tx, campaign: str, cid: str, person_id: int) -> bool:
    if held.already_queued(tx, campaign, cid, person_id):
        return True
    return tx.execute(
        "SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s",
        dict(p=person_id, c=campaign, cid=cid)).fetchone() is not None


def _log_push(tx, campaign: str, cid: str, person_id: int) -> bool:
    return tx.execute(
        """INSERT INTO push_send_log (person_id, campaign, campaign_id)
           VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
        dict(p=person_id, c=campaign, cid=cid)).fetchone() is not None


def _footer(unsub: str) -> str:
    return held.footer("You're getting this because of your Ahavah notification settings.",
                       unsub, 'Turn off notification emails')


def match_reminder_html(days: int, cta_url: str, unsubscribe_url: str) -> str:
    body = f"""
{chip("Your match")}

{title_image("title-match.png", "title-match-wht.png", "It's a match.", 460)}

{held.para(f"You matched with someone {days} days ago, and neither of you has written yet.")}

{held.para("They liked you too. A short hello is enough to start.", bottom=24)}

{button("Say hello", cta_url)}
"""
    return render(title=MATCH_SUBJECT, preheader="Neither of you has written yet.",
                  body_html=body, footer_html=_footer(unsubscribe_url))


MATCH_SUBJECT = "Your match is waiting for a hello"


def message_subject(people: int) -> str:
    return ("Someone is waiting for your reply" if people == 1
            else f"{people} people are waiting for your reply")


def message_reminder_html(people: int, cta_url: str, unsubscribe_url: str) -> str:
    lede = ("You have an unread message on Ahavah from 1 person." if people == 1
            else f"You have unread messages on Ahavah from {people} people.")
    body = f"""
{chip("Messages")}

{title_image("title-message.png", "title-message-wht.png", "You've got mail.", 460)}

{held.para(lede)}

{held.para("Open Ahavah to read and reply.", bottom=24)}

{button("Read your messages", cta_url)}
"""
    return render(title=message_subject(people), preheader="A conversation is waiting for you.",
                  body_html=body, footer_html=_footer(unsubscribe_url))


def _deliver(tx, *, campaign: str, cid: str, row, push: dict, subject: str, html_for) -> bool:
    """Push or email one reminder. Returns True when something was sent or
    queued. `html_for(cta_url, unsub_url)` builds the email only when it is
    needed, so a push mints no campaign link."""
    pid = row['person_id']
    if row['push_on'] and row['has_push'] and PUSH_READY():
        if _log_push(tx, campaign, cid, pid):
            # After the commit, never inside it (held.after_commit).
            held.after_commit(lambda: _push(pid, push['title'], push['body'],
                                            push['url'], push['kind']))
            return True
        return False
    if not row['email_on']:
        return False
    target = f"{WEB_BASE_URL}{push['url']}"
    cta = make_campaign_link(tx, campaign, target, pid)
    unsub = unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL)
    return held.queue(tx, campaign=campaign, campaign_id=cid, person_id=pid, email=row['email'],
                      subject=subject, html=html_for(cta, unsub), from_addr=FROM_ADDR,
                      unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None


def queue_match_reminders(tx, now: datetime) -> int:
    if not enabled(MATCH) or not held.in_reminder_window(now):
        return 0
    n = 0
    for r in tx.execute(_Q_MATCHES, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall():
        stage = _stage(int(r['days']))
        if stage is None:
            continue
        cid = f"{MATCH}-{r['match_id']}-{stage}"
        if _already(tx, MATCH, cid, r['person_id']):
            continue
        days = int(r['days'])
        if _deliver(tx, campaign=MATCH, cid=cid, row=r, push=MATCH_PUSH, subject=MATCH_SUBJECT,
                    html_for=lambda cta, unsub, d=days: match_reminder_html(d, cta, unsub)):
            n += 1
    return n


def queue_message_reminders(tx, now: datetime) -> int:
    if not enabled(MESSAGE) or not held.in_reminder_window(now):
        return 0
    n = 0
    for r in tx.execute(_Q_MESSAGES, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall():
        stage = _stage(int(r['days']))
        if stage is None:
            continue
        cid = f"{MESSAGE}-{r['newest_s']}-{stage}"
        if _already(tx, MESSAGE, cid, r['person_id']):
            continue
        people = int(r['people'])
        if _deliver(tx, campaign=MESSAGE, cid=cid, row=r, push=MESSAGE_PUSH,
                    subject=message_subject(people),
                    html_for=lambda cta, unsub, k=people: message_reminder_html(k, cta, unsub)):
            n += 1
    return n


def preview_match(to: str) -> tuple[str, str]:
    """The proof: a match 3 days old. Sample data, nothing stored."""
    return MATCH_SUBJECT, match_reminder_html(
        3, f"{WEB_BASE_URL}/matches", unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))


def preview_message(to: str) -> tuple[str, str]:
    """The proof: 1 unread conversation. Sample data, nothing stored."""
    return message_subject(1), message_reminder_html(
        1, f"{WEB_BASE_URL}/inbox", unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
