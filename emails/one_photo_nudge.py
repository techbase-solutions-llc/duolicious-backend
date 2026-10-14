"""The one-photo nudge (health review, 13 Oct 2026, finding 38).

Profiles with one photo or none are passed almost every time: on women's
decisions about men, 0 or 1 approved photo drew 5 likes in 121 decisions,
2 or more drew 25 in 193. Members with no approved photo already left the
deck (Wave 2). This asks members with exactly one approved photo, and no
second photo waiting for moderation, to add another.

Cadence: at most once in 30 days and twice ever, so it never becomes a
reminder that keeps coming back. Tuesday from 12:00 UTC. Unsubscribe scope
`campaigns`. Held: nothing is queued unless AHAVAH_ONE_PHOTO_NUDGE_ENABLED is
on.

The copy makes no numeric claim: the figures above are about one side's
decisions only.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime

from emails.base import button, chip, render, suppressed_sql_pattern, title_image
from service.admin.queries.members import member_sql
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns import held
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'one_photo'
SWITCH = 'one_photo'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
TARGET = f"{WEB_BASE_URL}/profile/edit"
SUBJECT = "Add a second photo to your Ahavah profile"
RESEND_DAYS = 30
MAX_SENDS = 2

_Q_DUE = f"""
    SELECT p.id AS person_id, p.email
      FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND {member_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND (SELECT count(*) FROM photo ph
             WHERE ph.person_id = p.id AND ph.moderation_status = 'approved') = 1
       AND NOT EXISTS (SELECT 1 FROM photo ph
                        WHERE ph.person_id = p.id
                          AND ph.moderation_status IN ('pending', 'manual_review'))
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{CAMPAIGN}'
                          AND l.sent_at > NOW() - make_interval(days => {RESEND_DAYS}))
       AND (SELECT count(*) FROM email_send_log l
             WHERE l.person_id = p.id AND l.campaign = '{CAMPAIGN}') < {MAX_SENDS}
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def one_photo_html(cta_url: str, unsubscribe_url: str) -> str:
    body = f"""
{chip("Your profile")}

{title_image("title-finish-profile.png", "title-finish-profile-wht.png", "Finish your profile.", 447)}

{held.para("Your profile has 1 photo.")}

{held.para("A second photo helps people see who you are before they decide to say hello.", bottom=24)}

{button("Add a photo", cta_url)}
"""
    return render(title=SUBJECT, preheader="A second photo helps people see who you are.",
                  body_html=body,
                  footer_html=held.footer("You're receiving this because you're a member of Ahavah.",
                                          unsubscribe_url))


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
                      email=r['email'], subject=SUBJECT, html=one_photo_html(cta, unsub),
                      from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None:
            n += 1
    return n


def preview(to: str) -> tuple[str, str]:
    """The proof. Nothing stored."""
    return SUBJECT, one_photo_html(TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
