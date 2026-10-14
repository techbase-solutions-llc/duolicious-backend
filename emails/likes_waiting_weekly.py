"""Likes waiting, weekly (health review, 13 Oct 2026, findings 57 and 64).

A member who has been away 3 days or more, and who has at least 1 like that
arrived after they were last online, is told how many likes are waiting.
Never who: no name, no photo, nothing about the likers, and the likers are
told nothing. When members who fit what they are looking for (their gender
and age preferences) have joined since their last visit, one line says how
many, so that nobody gets this and a separate newcomer email in one week.

Held: nothing is queued unless AHAVAH_LIKES_WAITING_ENABLED is on
(service/campaigns/switches.py). Thursday from 12:00 UTC, once per ISO
week (service/campaigns/held.py has the caps). Unsubscribe scope
`campaigns`. Replaces the one-off emails/send_likes_waiting.py for the
scheduled send; that script is left as it was.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime

from emails.base import button, callout, chip, render, suppressed_sql_pattern, title_image
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns import held
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded, count_newcomers_since
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'likes_waiting'
SWITCH = 'likes_waiting'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
OFFLINE_DAYS = 3
TARGET = f"{WEB_BASE_URL}/matches?tab=likes"

# Unanswered likes by the rules of the Liked you tab
# (service/decisions Q_LIST_INCOMING_LIKES): not liked back, no block either
# way, the liker still activated, no match between them.
_Q_DUE = f"""
    WITH waiting AS (
        SELECT l.liked_id AS pid, count(*) AS n, max(l.created_at) AS newest
          FROM liked l
          JOIN person liker ON liker.id = l.liker_id AND liker.activated
         WHERE NOT EXISTS (SELECT 1 FROM liked rev
                            WHERE rev.liker_id = l.liked_id AND rev.liked_id = l.liker_id)
           AND NOT is_blocked_pair(l.liked_id, l.liker_id)
           AND NOT EXISTS (SELECT 1 FROM ahavah_match m
                            WHERE m.user_a_id = LEAST(l.liker_id, l.liked_id)
                              AND m.user_b_id = GREATEST(l.liker_id, l.liked_id))
         GROUP BY l.liked_id
    )
    SELECT p.id AS person_id, p.email, p.last_online_time, w.n AS likes
      FROM person p
      JOIN waiting w ON w.pid = p.id
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND lower(p.email) <> ALL(%(ex)s)
       AND p.last_online_time < NOW() - make_interval(days => {OFFLINE_DAYS})
       AND w.newest > p.last_online_time
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def subject_for(likes: int) -> str:
    return "Someone likes you on Ahavah" if likes == 1 else f"{likes} people like you on Ahavah"


def likes_waiting_weekly_html(likes: int, new_fits: int, cta_url: str, unsubscribe_url: str) -> str:
    if likes == 1:
        lede = "1 person has liked your profile and is waiting for an answer."
    else:
        lede = f"{likes} people have liked your profile and are waiting for an answer."
    fit = ''
    if new_fits == 1:
        fit = held.para("1 new person who fits what you are looking for has joined since your last visit.")
    elif new_fits > 1:
        fit = held.para(f"{new_fits} new people who fit what you are looking for have joined since your last visit.")
    body = f"""
{chip("Likes waiting")}

{title_image("title-like.png", "title-like-wht.png", "Someone likes you.", 430)}

{held.para(lede)}

{fit}

{held.para("A like becomes a conversation when you answer it.", bottom=24)}

{button("See who likes you", cta_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Only you can see your likes. Nobody is told when you look.")}
"""
    return render(
        title=subject_for(likes),
        preheader="See who, and decide for yourself.",
        body_html=body,
        footer_html=held.footer("You're receiving this because members liked your profile.", unsubscribe_url),
    )


def campaign_id(now: datetime) -> str:
    return f"{CAMPAIGN}-{held.week_suffix(now)}"


def queue_due(tx, now: datetime) -> int:
    """Queue this week's email for every member due one. Returns how many
    were queued. Nothing at all while the switch is off or outside
    Thursday's window."""
    if not enabled(SWITCH) or not held.in_weekly_window(now, CAMPAIGN):
        return 0
    cid = campaign_id(now)
    rows = tx.execute(_Q_DUE, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall()
    queued = 0
    for r in rows:
        if held.already_queued(tx, CAMPAIGN, cid, r['person_id']):
            continue
        fits = count_newcomers_since(tx, r['person_id'], r['last_online_time'])
        cta = make_campaign_link(tx, CAMPAIGN, TARGET, r['person_id'])
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        if held.queue(tx, campaign=CAMPAIGN, campaign_id=cid, person_id=r['person_id'],
                      email=r['email'], subject=subject_for(int(r['likes'])),
                      html=likes_waiting_weekly_html(int(r['likes']), int(fits), cta, unsub),
                      from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None:
            queued += 1
    return queued


def preview(to: str) -> tuple[str, str]:
    """The proof: 2 likes and 3 new fits, sample data, nothing stored. The
    button goes straight to the page, since no campaign link is minted."""
    return subject_for(2), likes_waiting_weekly_html(2, 3, TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
