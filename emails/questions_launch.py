"""The quick questions launch email (TEC-1845, spec "Launch").

To every member who has not left campaign emails, once per member ever
(email_send_log campaign questions_launch), on a drop day from 12:00 UTC,
held behind AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED and the questions_live
master switch (service.questions.switch_on). Members away for more
than 30 days are included: for them it is a reason to come back.

Each option is its own campaign link to /q/{key}/{choice} on the web app,
so clicks count per option. The click alone records nothing (mail scanners
open links); the page saves the answer once the member is signed in, and
never over an earlier one.

Brand shell, title image from Claude Design (never hand-rolled type), the
campaigns footer and unsubscribe. In SELF_CAPPED_CAMPAIGNS and queued
exempt: E2 goes to every member every Monday, so a 7-day cap would skip
nearly everyone. Owner decision 1: no line names Sunday.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from emails.base import INK, LIME, MUTED, SANS, chip, render, suppressed_sql_pattern, title_image
from service.admin.queries.members import member_sql
from service.campaigns import (held, make_campaign_link, suppressed_predicate_sql,
                               unsubscribed_predicate_sql)
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.questions import switch_on
from service.questions.copy import SAMPLE_QUESTION, in_sentence, short_question
from service.questions.schedule import barbados_today, current_drop, resting
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'questions_launch'
CAMPAIGN_ID = 'questions_launch'
SWITCH = 'questions_launch_email'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
# The title image's 1x width: 801 px at 2x, halved and rounded down. The
# design shows it at up to 420 px.
TITLE_WIDTH = 400

SUBJECT = "New on Ahavah: quick questions"
CHIP = "New in the app"
BODY = ("Each week a light question now waits for you in the app. Answer it with one tap, "
        "and once 5 members have answered you can see how the answers split. On someone's "
        "profile, answer the same questions to see what they picked. When you match, you both "
        "get one question to answer, so your first message has somewhere to start.")
TAP_LINE = "Tap your answer. We'll save it once you're signed in."
# A small label, as E2 labels its sections ("New this week"): a heading tag
# would be hand-rolled display type (tests/test_email_templates_use_the_brand_shell.py).
ALSO_TITLE = "Also new on Ahavah"
# True while every member holds Premium; 14 lapse from 16 Dec (spec,
# decision 9), so the first line changes if the email goes later.
ALSO_NEW = ("See who liked you in Liked you, and like them back from their profile.",
            "Discover now keeps going past the first 10 profiles.",
            "A reminder when a match or a message is waiting for you.")


def preheader_for(question: dict) -> str:
    return f"This week's is {in_sentence(short_question(question).rstrip('?'))}. Tap your answer."


def _option_button(label: str, href: str) -> str:
    """The one place a label may wrap (brief, section 1): a long option
    grows the button taller rather than running off a phone screen."""
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 12px;">
      <tr><td align="center" bgcolor="{LIME}" style="border-radius:999px;">
        <a href="{href}" target="_blank" style="display:block;padding:16px 24px;font-family:{SANS};font-size:17px;font-weight:800;line-height:1.3;color:{INK};text-decoration:none;border-radius:999px;white-space:normal;">{escape(label)}</a>
      </td></tr>
    </table>"""


def launch_html(question: dict, links: list[tuple[str, str]], unsubscribe_url: str) -> str:
    buttons = ''.join(_option_button(label, href) for label, href in links)
    also = ''.join(held.para(f"&#8226;&nbsp; {line}", size=16, bottom=8) for line in ALSO_NEW)
    body = f"""
{chip(CHIP)}

{title_image("title-quick-questions.png", "title-quick-questions-wht.png", "Quick questions.", TITLE_WIDTH)}

{held.para(BODY)}

{held.para(f"This week: {escape(in_sentence(question['text']))}", bottom=16)}

{buttons}

{held.para(TAP_LINE, size=15, muted=True, bottom=28)}

<p class="e-text" style="margin:0 0 8px;font-family:{SANS};font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};font-weight:700;">{ALSO_TITLE}</p>
{also}
"""
    return render(title=SUBJECT, preheader=preheader_for(question), body_html=body,
                  footer_html=held.footer("You're receiving this because you're a member of Ahavah.",
                                          unsubscribe_url))


def _target(question: dict, choice_key: str) -> str:
    return f"{WEB_BASE_URL.rstrip('/')}/q/{question['key']}/{choice_key}"


_Q_DUE = f"""
    SELECT p.id AS person_id, p.email
      FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND {member_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{CAMPAIGN}')
     ORDER BY p.id
"""


def queue_due(tx, now: datetime) -> int:
    if not switch_on(SWITCH) or now.hour < held.SEND_HOUR_UTC or resting(now):
        return 0
    drop = current_drop(tx, now)
    if drop is None or drop['live_on'] != barbados_today(now):
        return 0
    question = drop['question']
    n = 0
    for r in tx.execute(_Q_DUE, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall():
        pid = r['person_id']
        if held.already_queued(tx, CAMPAIGN, CAMPAIGN_ID, pid):
            continue
        links = [(o['label'], make_campaign_link(tx, CAMPAIGN, _target(question, o['key']), pid))
                 for o in question['options']]
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        if held.queue(tx, campaign=CAMPAIGN, campaign_id=CAMPAIGN_ID, person_id=pid, email=r['email'],
                      subject=SUBJECT, html=launch_html(question, links, unsub), from_addr=FROM_ADDR,
                      unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None:
            n += 1
    return n


def preview(to: str) -> tuple[str, str]:
    """The proof: week 1's question, buttons straight to the answer page,
    nothing stored. scripts/send_question_proofs.py makes those buttons
    inert, with the unsubscribe link, before the owner gets it."""
    q = SAMPLE_QUESTION
    return SUBJECT, launch_html(q, [(o['label'], _target(q, o['key'])) for o in q['options']],
                                unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
