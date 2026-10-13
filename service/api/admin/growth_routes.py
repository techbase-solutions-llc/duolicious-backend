from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import duotypes as t
import psycopg
from flask import abort, jsonify, request

from database import api_tx
from service.admin import require_admin, record_audit
from service.api.decorators import aget, apost
from service.campaigns import count_sendable
from service.campaigns.runner import SEND_AUDIT_ACTION
from service.campaigns.schedule import COMMUNITY_WEEKLY_ENABLED, next_send_at
from service.campaigns.weekid import week_campaign_id
from service.growth.queries import growth_stats
import emails.send_spotlight_announcement as e1
import emails.send_community_weekly as e2
import emails.send_reinvite as e3
import emails.send_notifications_nudge as e6

@aget('/admin/growth/stats')
def get_admin_growth_stats(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return growth_stats(tx)

_CAMPAIGNS = {'e1': e1, 'e2': e2, 'e3': e3, 'e6': e6}

# Deliberately simple: this only has to reject things that are obviously not
# an address before we hand one to SMTP. Real validation is the mail server's
# job, and a preview is admin-only.
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# e2 is the only campaign on a cadence. e1 announces a specific thing and e3
# targets a chosen cohort, so both are operator-run by design and say so.
#
# This exists because "last sent 24 Sep" with nothing beside it reads like a
# healthy weekly rhythm whether or not anything will ever send the next one.
# For months nothing did, and the row looked the same either way.
#
# `overdue` closes the mirror image of that defect. A cron container that is
# down for the whole Monday window loses the week silently: no queued rows, no
# error, nothing logged, while the row goes on printing "Next Monday, 08:00"
# and the last-sent date quietly stops advancing. Eight days is one full
# cadence plus a day of slack, so it cannot fire on a healthy week however
# late in the window the send landed.
_OVERDUE_AFTER = timedelta(days=8)

def _schedule_for(campaign: str, now: datetime, last_sent_at: datetime | None) -> dict | None:
    if campaign != 'e2':
        return None
    if not COMMUNITY_WEEKLY_ENABLED:
        return dict(enabled=False, next_send_at=None, overdue=False)
    overdue = last_sent_at is None or (now - last_sent_at) > _OVERDUE_AFTER
    return dict(enabled=True, next_send_at=next_send_at(now).isoformat(),
                overdue=overdue)

_Q_LAST_SENT = """
    SELECT campaign, max(sent_at) AS at,
           (array_agg(campaign_id ORDER BY sent_at DESC))[1] AS cid,
           count(*) AS n,
           count(DISTINCT person_id) AS people
      FROM email_send_log GROUP BY campaign
"""

# What one run achieved. `reached` is the members its mail was accepted for
# (the drain writes the send log on acceptance). `clicks` counts clicks on
# the /s/ links that run's own mail carried, found in the outbox payload,
# with bots left out as service.growth.queries.post_stats leaves them out.
# A campaign mints its CTA links under its own key as the link kind and with
# the recipient as the link's subject (each module's build_for), so each
# outbox row is only searched for its own member's few links. Matching on
# kind alone searched every link the campaign ever minted in every mail of
# the run, about 53 more e2 links a week. `links` is 0 when the mail carried
# no tracked link (e1's confirm link, or a run from before the outbox), and
# then there is no click figure to give.
_Q_RUN_RESULTS = """
    WITH run_links AS (
        SELECT DISTINCT l.key
          FROM email_outbox o
          JOIN campaign_link l
            ON l.kind = o.campaign
           AND l.subject_person_id = o.person_id
           AND strpos(o.payload->>'html', '/s/' || l.key) > 0
         WHERE o.campaign = %(c)s AND o.campaign_id = %(cid)s
    )
    SELECT (SELECT count(*) FROM email_send_log
             WHERE campaign = %(c)s AND campaign_id = %(cid)s) AS reached,
           (SELECT count(*) FROM run_links) AS links,
           (SELECT count(*) FROM campaign_click c JOIN run_links r ON r.key = c.link_key
             WHERE c.ua_class <> 'bot') AS clicks
"""

# The id a send pressed now would use. The Send button keys all four
# campaigns by ISO week (ahavah-admin src/lib/growth-api.ts campaignId), and
# the e2 cron and CLI compute the same id for e2, so a member who already has
# this week's id is skipped as a repeat. Only e2 needs that check here: its 6
# day cap is shorter than an ISO week, so a member can be past the cap and
# still hold this week's e2. The 7 day cap on e1, e3 and e6 already covers
# any send in the same ISO week, so for them no id gives the same figure.
_NEXT_RUN_ID = {'e2': lambda now: week_campaign_id(now, 'e2')}


def _run_results(tx, campaign: str, campaign_id: str | None) -> tuple[int | None, int | None]:
    if not campaign_id:
        return None, None
    r = tx.execute(_Q_RUN_RESULTS, dict(c=campaign, cid=campaign_id)).fetchone()
    return int(r['reached']), (int(r['clicks']) if r['links'] else None)


@aget('/admin/growth/emails')
def get_admin_growth_emails(s: t.SessionInfo):
    """One row per campaign (health review, 13 Oct 2026, finding 3).

    For the admin-run campaigns (e1, e2, e3, e6):
      eligible_now      the cohort a send is aimed at, unsubscribed and
                        suppressed addresses already out, before the cap
      would_reach_now   who a send pressed now would queue: eligible_now
                        less members inside the campaign's frequency cap
                        (or already sent this run's id)
      last_run_reached  members the last run's mail was accepted for
      last_run_clicks   clicks on the links in that run's mail, bots out;
                        null when the mail carried no tracked link
      recipients        kept equal to eligible_now for the admin build that
                        reads it, until the redesigned table lands

    For the rows the platform sends one member at a time (e4, e5, welcome,
    referral) there is no cohort and no run, so those four are null;
    `recipients` stays every row ever sent and `people_reached` counts
    distinct people. `people_reached` is on every row."""
    require_admin(s)
    with api_tx('read committed') as tx:
        last_sent = {r['campaign']: r for r in tx.execute(_Q_LAST_SENT).fetchall()}
    # recipients() opens its own transaction per campaign, so it must be
    # called OUTSIDE any block here: the api connection lock is not
    # reentrant and nesting would deadlock the request. The materialised
    # list is what lets would_reach_now apply the runner's own rules to
    # exactly the people a send would be handed.
    now = datetime.now(timezone.utc)
    cohorts = {key: [r['person_id'] for r in mod.recipients()] for key, mod in _CAMPAIGNS.items()}
    out = []
    with api_tx('read committed') as tx:
        for key, mod in _CAMPAIGNS.items():
            last = last_sent.get(key)
            ids = cohorts[key]
            next_id = _NEXT_RUN_ID.get(key)
            would_reach = count_sendable(tx, ids, key, next_id(now) if next_id else None,
                                         cap_days=getattr(mod, 'CAP_DAYS', 7))
            reached, clicks = _run_results(tx, key, last['cid'] if last else None)
            out.append(dict(campaign=key, recipients=len(ids),
                            eligible_now=len(ids), would_reach_now=would_reach,
                            last_run_reached=reached, last_run_clicks=clicks,
                            people_reached=int(last['people']) if last else 0,
                            last_sent_at=last['at'].isoformat() if last and last['at'] else None,
                            last_campaign_id=last['cid'] if last else None, system=False,
                            schedule=_schedule_for(key, now, last['at'] if last else None)))
    # e4 (the member invite) and e5 (the card-went-live receipt) are sent by
    # the platform itself, not run from this admin screen: they have no
    # recipients()/recipient_count() module to ask, so their count comes
    # straight from the email_send_log rows the query above already grouped,
    # and they carry system=True so the Growth tab can tell them apart from
    # the three admin-run campaigns above.
    # `welcome` (the member welcome at finish-onboarding) and `referral` (the
    # invite link a week in, from the referralintro cron) joined them on
    # 1 Oct 2026 (TEC-1613): both go through the outbox now, so they have a
    # send log to read.
    for key in ('e4', 'e5', 'welcome', 'referral'):
        last = last_sent.get(key)
        out.append(dict(campaign=key, recipients=int(last['n']) if last else 0,
                        eligible_now=None, would_reach_now=None,
                        last_run_reached=None, last_run_clicks=None,
                        people_reached=int(last['people']) if last else 0,
                        last_sent_at=last['at'].isoformat() if last and last['at'] else None,
                        last_campaign_id=last['cid'] if last else None, system=True,
                        schedule=None))
    return dict(campaigns=out)

@apost('/admin/growth/emails/<campaign>/preview')
def post_admin_growth_email_preview(s: t.SessionInfo, campaign: str):
    require_admin(s)
    mod = _CAMPAIGNS.get(campaign) or abort(404)
    to = (request.get_json(silent=True) or {}).get('to') or abort(400)
    if not isinstance(to, str) or not _EMAIL_RE.match(to):
        abort(400)
    preview_row = getattr(mod, 'preview_row', None)
    row = preview_row(to) if preview_row else dict(person_id=0, email=to, name='Preview')
    subject, html = mod.build_for(row)
    from smtp import make_aws_smtp
    make_aws_smtp().send(subject=subject, body=html, to_addr=to, from_addr=mod.FROM_ADDR)
    return dict(ok=True)

@apost('/admin/growth/emails/<campaign>/send')
def post_admin_growth_email_send(s: t.SessionInfo, campaign: str):
    """Queue a run and return immediately (F07). Nothing here talks to SMTP
    any more: the response reports how many messages were QUEUED, and the
    `emailoutbox` cron sends them. Progress is read back from
    `/admin/growth/emails/<campaign>/status/<campaign_id>`."""
    require_admin(s)
    mod = _CAMPAIGNS.get(campaign) or abort(404)
    body = request.get_json(silent=True) or {}
    cid = body.get('campaign_id') or abort(400)
    dry = bool(body.get('dry_run', True))
    from service.campaigns.runner import run_campaign
    from service.unsubscribe import make_url as _unsub_url
    from service.config import WEB_BASE_URL
    # Wave 3d Task 3 (Runtime 4d): a second submit of the same campaign_id
    # racing the first meets a row the first has just queued but its own
    # snapshot cannot see, and dies inside outbox.enqueue (SerializationFailure
    # under REPEATABLE READ, the evidence's case). Nobody is queued twice, the
    # outbox key holds that; the loser answers 409 send_in_progress instead of
    # 500. run_campaign commits one transaction per recipient, so by the time
    # the error reaches this except only the failing recipient's transaction
    # has rolled back; the recipients this submit queued before it are
    # committed and stay queued. Not retried here: the other submit is
    # carrying the run. Re-submitting the same campaign_id is safe and
    # finishes a half-queued cohort: rows already queued are skipped by the
    # outbox key, and every recipient still missing is queued.
    try:
        res = run_campaign(api_tx, campaign, cid, mod.recipients(), mod.build_for, send=not dry,
                           from_addr=mod.FROM_ADDR,
                           unsub_scope=mod.UNSUB_SCOPE,
                           cap_days=getattr(mod, 'CAP_DAYS', 7),
                           list_unsubscribe=lambda e: f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{_unsub_url(mod.UNSUB_SCOPE, e, WEB_BASE_URL)}>",
                           post_send=getattr(mod, 'post_send', None))
    except (psycopg.errors.UniqueViolation, psycopg.errors.SerializationFailure):
        return dict(error='send_in_progress'), 409
    # The audit row is written AFTER the run, not inside it, on purpose: a run
    # spans one transaction per recipient (see service/campaigns/runner.py), so
    # there is no single transaction the audit could share. `res` already
    # carries campaign_id and dry_run, so only `campaign` is added here.
    with api_tx() as tx:
        record_audit(tx, s, SEND_AUDIT_ACTION, metadata=dict(campaign=campaign, **res))
    return res


@aget('/admin/growth/emails/<campaign>/status/<campaign_id>')
def get_admin_growth_email_status(s: t.SessionInfo, campaign: str, campaign_id: str):
    """Where a queued run actually got to. `acceptance_unknown` is the one
    that needs a human: those messages were reserved by a drain that never
    reported back, so whether they reached the member is genuinely unknown
    and the outbox refuses to guess (F08)."""
    require_admin(s)
    _CAMPAIGNS.get(campaign) or abort(404)
    from service.campaigns import outbox
    with api_tx('read committed') as tx:
        return outbox.status(tx, campaign, campaign_id)


@aget('/admin/growth/emails/unknown')
def get_admin_growth_emails_unknown(s: t.SessionInfo):
    """Task 7 (Wave 3b): the cross-campaign view of F08's acceptance_unknown
    mail. The status endpoint above answers the same question for one run,
    but only for a campaign_id the operator already knows to ask about; this
    lists every run that has at least one row genuinely stuck, without that."""
    require_admin(s)
    from service.campaigns import outbox
    with api_tx('read committed') as tx:
        return jsonify(outbox.unknown_summary(tx))
