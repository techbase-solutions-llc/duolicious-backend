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
from service.growth import email_outcomes
from service.growth.queries import growth_stats
from service.growth.sources import source_rows
import emails.send_spotlight_announcement as e1
import emails.send_community_weekly as e2
import emails.send_reinvite as e3
import emails.send_notifications_nudge as e6

@aget('/admin/growth/stats')
def get_admin_growth_stats(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return growth_stats(tx)

@aget('/admin/growth/sources')
def get_admin_growth_sources(s: t.SessionInfo):
    """The Sources table (TEC-1845): leads, sign-ups and members who reached
    a two-sided conversation, per source on one taxonomy."""
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(sources=source_rows(tx))


@aget('/admin/growth/push')
def get_admin_growth_push(s: t.SessionInfo):
    """Push on, failing and new since a day (frame G.1). Members only,
    except `with_push_counting_staff`, which the tile labels so."""
    require_admin(s)
    from datetime import date
    from service.admin.queries.push import PUSH_BANNER_SHIPPED, Q_PUSH
    from service.growth.queries import _excluded
    since = request.args.get('since') or PUSH_BANNER_SHIPPED
    try:
        date.fromisoformat(since)
    except ValueError:
        abort(400)
    with api_tx('read committed') as tx:
        row = tx.execute(Q_PUSH, dict(ex=_excluded(), since=since)).fetchone()
    return dict(row, since=since)


@aget('/admin/growth/tiers')
def get_admin_growth_tiers(s: t.SessionInfo):
    """Members per verification tier, none first (frame G.1)."""
    require_admin(s)
    from service.admin.queries.profiles import Q_VERIFICATION_TIERS
    from service.growth.queries import _excluded
    with api_tx('read committed') as tx:
        rows = tx.execute(Q_VERIFICATION_TIERS, dict(ex=_excluded())).fetchall()
    return dict(tiers=[dict(r) for r in rows])


@aget('/admin/growth/tools')
def get_admin_growth_tools(s: t.SessionInfo):
    """Couple tools (TEC-1845): per mode, sessions started, completed,
    saved, invite links made, invite emails sent, sessions a guest joined,
    guests and share-link openings; sign-ups per tool source. Counts only,
    never an answer or a name."""
    require_admin(s)
    from service.tools.admin import tool_counts
    with api_tx('read committed') as tx:
        return tool_counts(tx)


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

# The id a send pressed now would use. The Send button keys all four
# campaigns by ISO week (ahavah-admin src/lib/growth-api.ts campaignId), and
# the e2 cron and CLI compute the same id for e2, so a member who already has
# this week's id is skipped as a repeat. Only e2 needs that check here: its 6
# day cap is shorter than an ISO week, so a member can be past the cap and
# still hold this week's e2. The 7 day cap on e1, e3 and e6 already covers
# any send in the same ISO week, so for them no id gives the same figure.
_NEXT_RUN_ID = {'e2': lambda now: week_campaign_id(now, 'e2')}


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
    distinct people. `people_reached` is on every row.

    TEC-1897 adds, per admin-run row, last_run_came_back (recipients online
    since their send), last_run_came_back_7d (online within 7 days of it;
    null before the per-day record began) and last_run_push_turned_on (e6
    only), and `came_back` on the system rows (people online since their
    first send of that email)."""
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
            cid = last['cid'] if last else None
            reached, clicks = email_outcomes.run_results(tx, key, cid)
            outcome = email_outcomes.run_outcomes(tx, key, cid)
            out.append(dict(campaign=key, recipients=len(ids),
                            eligible_now=len(ids), would_reach_now=would_reach,
                            last_run_reached=reached, last_run_clicks=clicks,
                            last_run_came_back=outcome['came_back'],
                            last_run_came_back_7d=outcome['came_back_7d'],
                            last_run_push_turned_on=outcome['push_turned_on'],
                            came_back=None,
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
    with api_tx('read committed') as tx:
        came_back = {key: email_outcomes.came_back_all_time(tx, key)
                     for key in ('e4', 'e5', 'welcome', 'referral')}
    for key in ('e4', 'e5', 'welcome', 'referral'):
        last = last_sent.get(key)
        out.append(dict(campaign=key, recipients=int(last['n']) if last else 0,
                        eligible_now=None, would_reach_now=None,
                        last_run_reached=None, last_run_clicks=None,
                        last_run_came_back=None, last_run_came_back_7d=None,
                        last_run_push_turned_on=None,
                        came_back=came_back[key],
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


@aget('/admin/growth/emails/<campaign>/runs')
def get_admin_growth_email_runs(s: t.SessionInfo, campaign: str):
    """One email's run history (frame G.4): date, campaign id, how it was
    started, reached, clicks and came back, newest first, and the last 30
    days in one line. Admin-run emails only."""
    require_admin(s)
    _CAMPAIGNS.get(campaign) or abort(404)
    with api_tx('read committed') as tx:
        return dict(runs=email_outcomes.run_history(tx, campaign),
                    last_30_days=email_outcomes.last_30_days(tx, campaign))


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
