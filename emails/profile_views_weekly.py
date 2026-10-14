"""Profile views, weekly (health review, 13 Oct 2026, finding 65).

The settings page offers an Email switch for profile views, and 4 members
turned it on, but nothing ever sent on it. This is what it sends: once a
week, how many people viewed the member's profile in the last 7 days.
Never who. The visits counted are the ones the Views list would show the
member (service/person/sql Q_VISITORS): not invisible, the visitor
activated, no block either way, and the visitor willing to be shown to
strangers or already in a conversation. Staff visits are not counted.

Only for members who turned the Email switch on (email_profile_views; its
default is off), so the unsubscribe scope is `notifications`, the scope of
that switch. Held: nothing is queued unless
AHAVAH_PROFILE_VIEW_EMAIL_ENABLED is on. Wednesday from 12:00 UTC, once per
ISO week.

The settings footnote says email reaches a member only when a push cannot;
this weekly count goes whether or not they have push. The per-view push is
unchanged.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime

from emails.base import button, callout, chip, render, suppressed_sql_pattern
from service.admin.queries.members import member_sql
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns import held
from service.campaigns.switches import enabled
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'profile_views'
SWITCH = 'profile_views'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = None
TARGET = f"{WEB_BASE_URL}/views"

_Q_DUE = f"""
    WITH views AS (
        SELECT v.object_person_id AS pid, count(DISTINCT v.subject_person_id) AS n
          FROM visited v
          JOIN person viewer ON viewer.id = v.subject_person_id
         WHERE v.updated_at > NOW() - interval '7 days'
           AND NOT v.invisible
           AND viewer.activated
           AND viewer.id <> v.object_person_id
           AND {member_sql('viewer')}
           AND NOT is_blocked_pair(viewer.id, v.object_person_id)
           AND (NOT viewer.hide_me_from_strangers
                OR EXISTS (SELECT 1 FROM messaged m
                            WHERE m.subject_person_id = viewer.id
                              AND m.object_person_id = v.object_person_id))
         GROUP BY v.object_person_id
    )
    SELECT p.id AS person_id, p.email, w.n AS views
      FROM person p
      JOIN views w ON w.pid = p.id
      JOIN notification_preference np ON np.person_id = p.id AND np.email_profile_views
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND {member_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def subject_for(views: int) -> str:
    return ("Someone viewed your profile this week" if views == 1
            else f"{views} people viewed your profile this week")


def profile_views_html(views: int, cta_url: str, unsubscribe_url: str) -> str:
    lede = ("1 person viewed your profile on Ahavah this week." if views == 1
            else f"{views} people viewed your profile on Ahavah this week.")
    body = f"""
{chip("Profile views")}

<div style="height:18px;line-height:18px;">&nbsp;</div>

{held.para(lede, bottom=24)}

{button("See your views", cta_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("You get this because profile view emails are on in your settings. Turn them off any time in Settings, Notifications.")}
"""
    return render(title=subject_for(views), preheader="Your weekly count of profile views.",
                  body_html=body,
                  footer_html=held.footer("You're getting this because you turned on profile view emails.",
                                          unsubscribe_url, 'Turn off notification emails'))


def campaign_id(now: datetime) -> str:
    return f"{CAMPAIGN}-{held.week_suffix(now)}"


def queue_due(tx, now: datetime) -> int:
    if not enabled(SWITCH) or not held.in_weekly_window(now, CAMPAIGN):
        return 0
    cid = campaign_id(now)
    n = 0
    for r in tx.execute(_Q_DUE, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall():
        if held.already_queued(tx, CAMPAIGN, cid, r['person_id']):
            continue
        cta = make_campaign_link(tx, CAMPAIGN, TARGET, r['person_id'])
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        if held.queue(tx, campaign=CAMPAIGN, campaign_id=cid, person_id=r['person_id'],
                      email=r['email'], subject=subject_for(int(r['views'])),
                      html=profile_views_html(int(r['views']), cta, unsub),
                      from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None:
            n += 1
    return n


def preview(to: str) -> tuple[str, str]:
    """The proof: 3 views. Sample data, nothing stored."""
    return subject_for(3), profile_views_html(3, TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
