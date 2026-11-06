"""adminalerts - the owner's stale-post alert, and two retention sweeps
(TEC-1897).

Hourly, and off unless AHAVAH_ADMIN_ALERTS_CRON_ENABLED is on: while it is
off a tick does nothing at all. The alert goes to the owner alone
(emails/admin_alerts.py), behind its own switch, which is off until the
owner has seen its proof:

  * stale_post_alert: once per Barbados day, at or after 07:00, while a post
    has been in review for more than 24 hours (frame G.8).
  * support_alert (TEC-2115): a line in the same daily email while a
    support message has been open for more than 24 hours, the count only.
    With no post waiting it is the whole email, as a lone post line is.
    The two share the day's one log row, so the owner gets at most one
    alert email a day.

There is no report alert here: the report email antiabuse/lodgereport sends
to DUO_REPORT_EMAIL is the report alert, and the owner's "Email me when a
report arrives" is its switch.

THE LOG ROW IS THE GUARD. It is written in the transaction that decides to
send, before the send, so two ticks or two containers send once; a crash
between the commit and the send loses that one alert.

It also deletes api_error_tally rows older than 30 days and
member_online_day rows older than 120 days.
"""
from __future__ import annotations

import asyncio
import random
import re
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import api_tx
from emails import admin_alerts
from service.admin import record_system_audit
from service.campaigns.switches import enabled
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

ADMIN_ALERTS_POLL_SECONDS = env_int('DUO_CRON_ADMIN_ALERTS_POLL_SECONDS', 60 * 60)
STALE_HOURS = 24
SEND_HOUR = 7
BARBADOS = ZoneInfo('America/Barbados')

print(f'Hello from cron module: {__name__}')

_Q_STALE = """
    SELECT request_key, min(kind) AS kind, min(created_at) AS in_review_since,
           max((payload->>'count')::int) AS members
      FROM publishing_queue
     GROUP BY request_key
    HAVING bool_and(status = 'review')
       AND min(created_at) < NOW() - make_interval(hours => %(h)s)
     ORDER BY min(created_at)
"""

_Q_SUPPORT = """
    SELECT count(*)::int AS n
      FROM support_message
     WHERE status = 'open'
       AND received_at < NOW() - make_interval(hours => %(h)s)
"""

_Q_LOG = """
    INSERT INTO admin_alert_log (alert, alert_key) VALUES (%(a)s, %(k)s)
    ON CONFLICT DO NOTHING RETURNING alert
"""

_WEEK = re.compile(r'W(\d{1,2})')


def _smtp():
    from smtp import make_aws_smtp
    return make_aws_smtp()


def stale_posts(tx) -> list[dict]:
    out = []
    for r in tx.execute(_Q_STALE, dict(h=STALE_HOURS)).fetchall():
        m = _WEEK.search(r['request_key']) if r['kind'] == 'roundup' else None
        out.append(dict(request_key=r['request_key'], kind=r['kind'],
                        week=int(m.group(1)) if m else None, members=r['members'],
                        in_review_since=r['in_review_since']))
    return out


def open_support(tx) -> int:
    return tx.execute(_Q_SUPPORT, dict(h=STALE_HOURS)).fetchone()['n']


def queue_daily(tx, now: datetime):
    """(posts, support messages) to send, after writing the day's log row,
    or None. Each part counts only while its switch is on. The log row keeps
    the name 'stale_posts' it had before support joined the email, so the
    day of the deploy cannot send a second alert."""
    want_posts, want_support = enabled('stale_post_alert'), enabled('support_alert')
    if not (want_posts or want_support):
        return None
    local = now.astimezone(BARBADOS)
    if local.hour < SEND_HOUR:
        return None
    posts = stale_posts(tx) if want_posts else []
    support = open_support(tx) if want_support else 0
    if not posts and not support:
        return None
    if tx.execute(_Q_LOG, dict(a='stale_posts', k=local.date().isoformat())).fetchone() is None:
        return None
    record_system_audit(tx, 'cron', 'admin_alert.sent',
                        dict(alert='stale_posts', posts=len(posts), support=support))
    return posts, support


def prune(tx) -> None:
    tx.execute("DELETE FROM api_error_tally WHERE hour < NOW() - INTERVAL '30 days'")
    tx.execute("DELETE FROM member_online_day WHERE day < CURRENT_DATE - 120")


def _send(subject: str, html: str) -> None:
    _smtp().send(subject=subject, body=html, to_addr=admin_alerts.OWNER_TO,
                 from_addr=admin_alerts.FROM_ADDR)


def tick(now: datetime | None = None) -> dict:
    if not enabled('admin_alerts_cron'):
        return {'off': True}
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    try:
        with api_tx() as tx:
            daily = queue_daily(tx, now)
        posts, support = daily or ([], 0)
        out['stale_posts'], out['support'] = len(posts), support
        if daily:
            try:
                _send(*admin_alerts.daily_email(posts, support, now))
            except Exception:
                print(f'admin_alerts: daily alert not sent ({traceback.format_exc()})')
    except Exception:
        print(traceback.format_exc())
        out['stale_posts'] = out['support'] = 'error'
    try:
        with api_tx() as tx:
            prune(tx)
    except Exception:
        print(traceback.format_exc())
    return out


async def admin_alerts_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(tick))
        await asyncio.sleep(ADMIN_ALERTS_POLL_SECONDS)
