"""The send guard's Postgres side and its owner alert (send safeguards plan,
2 Nov 2026, task 1).

smtp/guard.py decides in Redis and keeps Postgres out of every send. This
module, run once a minute by service/cron/sendguard, does the rest:

  1. moves the gate's events from the Redis list `sg:events` (and any the
     gate kept in process while Redis was down) into `send_guard_event`;
  2. copies this hour's and last hour's tallies into `send_tally`;
  3. records every halt in `send_guard_halt`, and puts back in Redis any
     open halt Redis has lost (whether production Redis saves to disk was
     not checked, so nothing relies on it);
  4. sends the owner one alert covering every alertable event since the
     last tick: one email to each address in AHAVAH_ALERT_EMAILS and one web
     push to member AHAVAH_ALERT_PUSH_PERSON_ID. An alert email that fails
     and a push that reaches no device are recorded as `alert_failed`,
     which the stats route reports and the watchdog alerts on;
  5. once a Barbados day, from FEEDBACK_ALERT_FROM_HOUR, adds a
     `feedback_unanswered` event to that alert when any member report is
     still `new` after 24 hours (report rewards plan, 3 Nov 2026): report
     number, category and age only, never the message or an address. The
     event row is the day's marker, so it goes out once a day while any
     remain. In the same way, a `support_unanswered` event when any copied
     support message is still `open` after 24 hours (TEC-2115): message
     number and age only, never the subject, the text or an address. That
     read is skipped while the support inbox is switched off, and runs in
     its own savepoint;
  6. writes `sg:heartbeat`, last, and only when every step above completed.
     A tick that fails part way leaves the heartbeat stale, and the
     watchdog sees it.

Alerting from here rather than inside `send` avoids a circular import
between `smtp` and `service.notifications`.
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from typing import Callable, Optional

from database import api_tx
from smtp import guard

DEFAULT_ALERT_EMAILS = 'admin@techbaseltd.com'
DEFAULT_ALERT_PUSH_PERSON_ID = 18
EVENT_RETENTION_DAYS = 90
ALERT_RETRY_BACKOFF = 2
_EVENT_BATCH = 2000


def alert_emails() -> list[str]:
    raw = os.environ.get('AHAVAH_ALERT_EMAILS', '').strip() or DEFAULT_ALERT_EMAILS
    return [a for a in (x.strip() for x in raw.replace(',', ' ').split()) if a]


def alert_person_id() -> Optional[int]:
    raw = os.environ.get('AHAVAH_ALERT_PUSH_PERSON_ID', '').strip()
    if not raw:
        return DEFAULT_ALERT_PUSH_PERSON_ID
    try:
        return int(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

_Q_INSERT_EVENT = """
    INSERT INTO send_guard_event (at, channel, event, kind, rule, recipient, alert, detail)
    VALUES (%(at)s, %(channel)s, %(event)s, %(kind)s, %(rule)s, %(recipient)s, %(alert)s, %(detail)s)
"""


def _row(ev: dict) -> dict:
    return dict(at=ev.get('at') or datetime.now(timezone.utc).isoformat(),
                channel=ev.get('channel') or 'guard', event=ev.get('event') or 'unknown',
                kind=ev.get('kind'), rule=ev.get('rule'), recipient=ev.get('recipient'),
                alert=bool(ev.get('alert')), detail=json.dumps(ev.get('detail') or {}))


def insert_events(tx, events: list[dict]) -> None:
    for ev in events:
        tx.execute(_Q_INSERT_EVENT, _row(ev))


def _read_redis_events(r) -> list[str]:
    """The oldest events first. LPUSH puts the newest at index 0, so the
    tail holds the oldest; they are trimmed only after Postgres has them."""
    raw = r.lrange('sg:events', -_EVENT_BATCH, -1)
    return list(reversed(raw))


def _trim_redis_events(r, n: int) -> None:
    if n:
        r.ltrim('sg:events', 0, -n - 1)


# ---------------------------------------------------------------------------
# tallies
# ---------------------------------------------------------------------------

_Q_TALLY = """
    INSERT INTO send_tally (hour, channel, kind, outcome, count)
    VALUES (%(hour)s, %(channel)s, %(kind)s, %(outcome)s, %(count)s)
    ON CONFLICT (hour, channel, kind, outcome) DO UPDATE
       SET count = GREATEST(send_tally.count, EXCLUDED.count)
"""


def _flush_tallies(tx, r, now: datetime) -> None:
    from datetime import timedelta
    for t in (now - timedelta(hours=1), now):
        key = guard.utc_hour(t)
        hour = datetime.strptime(key, '%Y%m%d%H').replace(tzinfo=timezone.utc)
        for fld, count in (r.hgetall(f'sg:tally:{key}') or {}).items():
            channel, kind, outcome = fld.split('|', 2)
            tx.execute(_Q_TALLY, dict(hour=hour, channel=channel, kind=kind, outcome=outcome,
                                      count=int(count)))


# ---------------------------------------------------------------------------
# halts
# ---------------------------------------------------------------------------

_Q_RECORD_HALT = """
    INSERT INTO send_guard_halt (channel, scope, kind, set_at, reason)
    SELECT %(channel)s, %(scope)s, %(kind)s, %(set_at)s, %(reason)s
     WHERE NOT EXISTS (
           SELECT 1 FROM send_guard_halt
            WHERE channel = %(channel)s AND scope = %(scope)s
              AND kind IS NOT DISTINCT FROM %(kind)s
              AND (cleared_at IS NULL OR set_at >= %(set_at)s))
    ON CONFLICT DO NOTHING
"""

_Q_CLEARED_SINCE = """
    SELECT 1 FROM send_guard_halt
     WHERE channel = %(channel)s AND scope = %(scope)s AND kind IS NOT DISTINCT FROM %(kind)s
       AND cleared_at IS NOT NULL AND set_at >= %(set_at)s
       AND NOT EXISTS (SELECT 1 FROM send_guard_halt o
                        WHERE o.channel = %(channel)s AND o.scope = %(scope)s
                          AND o.kind IS NOT DISTINCT FROM %(kind)s AND o.cleared_at IS NULL)
"""

_Q_OPEN_HALTS = """
    SELECT channel, scope, kind, set_at, reason FROM send_guard_halt WHERE cleared_at IS NULL
"""


def _parse_halt(value: str) -> tuple[datetime, str]:
    try:
        v = json.loads(value)
        set_at = datetime.fromisoformat(v['set_at'])
        return set_at, v.get('reason') or ''
    except Exception:  # noqa: BLE001 -- a halt set by hand may be any string
        return datetime.now(timezone.utc), str(value)[:200]


def _sync_halts(tx, r) -> None:
    seen = set()
    for channel, kind, value in list(guard.iter_halts(r)):
        set_at, reason = _parse_halt(value)
        scope = 'all' if kind is None else 'kind'
        params = dict(channel=channel, scope=scope, kind=kind, set_at=set_at, reason=reason)
        if tx.execute(_Q_CLEARED_SINCE, params).fetchone():
            # Cleared in Postgres, but the clear died before it reached Redis.
            r.delete(guard.halt_key(channel, kind))
            continue
        tx.execute(_Q_RECORD_HALT, params)
        seen.add((channel, kind))
    for h in tx.execute(_Q_OPEN_HALTS).fetchall():
        if (h['channel'], h['kind']) in seen:
            continue
        r.set(guard.halt_key(h['channel'], h['kind']),
              json.dumps(dict(set_at=h['set_at'].isoformat(), reason=h['reason'] or '')))


_Q_CLEAR = """
    UPDATE send_guard_halt SET cleared_at = NOW(), cleared_by = %(by)s
     WHERE channel = %(channel)s AND scope = %(scope)s AND kind IS NOT DISTINCT FROM %(kind)s
       AND cleared_at IS NULL
    RETURNING id
"""


def clear_halt(channel: str, kind: Optional[str], *, by: str,
               audit: Optional[Callable] = None) -> bool:
    """Clear a halt in Postgres first, then Redis, and record who. True when
    there was a halt to clear. Postgres goes first so the cron never puts
    back a halt that is being cleared.

    `audit(tx)` runs inside the clearing transaction when a halt was
    cleared, so the admin route's audit row commits with the clear or not at
    all (TEC-2091)."""
    if channel not in ('email', 'push'):
        raise ValueError('channel must be email or push')
    scope = 'all' if kind is None else 'kind'
    with api_tx() as tx:
        closed = tx.execute(_Q_CLEAR, dict(channel=channel, scope=scope, kind=kind, by=by)).fetchall()
        in_redis = guard.clear_halt_redis(channel, kind)
        cleared = bool(closed) or in_redis
        if cleared:
            insert_events(tx, [dict(at=datetime.now(timezone.utc).isoformat(), channel=channel,
                                    event='cleared', kind=kind, rule=scope,
                                    detail=dict(by=by))])
            if audit is not None:
                audit(tx)
    return cleared


def set_halt(channel: str, kind: Optional[str], *, reason: str, by: str) -> bool:
    """A halt set by hand (scripts/mail_guard_halt.py). Recorded in Postgres
    by the next tick, like any other."""
    new = guard.set_halt(channel, kind, reason=f'{reason} (set by {by})')
    if new:
        guard.record_event('halt', channel=channel, kind=kind, alert=True, scope='all' if kind is None else 'kind',
                           reason=reason, by=by)
    return new


# ---------------------------------------------------------------------------
# member reports nobody has answered
# ---------------------------------------------------------------------------

FEEDBACK_ALERT_EVENT = 'feedback_unanswered'
# Barbados hour from which the day's reminder may go, so it does not arrive
# at midnight.
FEEDBACK_ALERT_FROM_HOUR = 9

_Q_BARBADOS_HOUR = "SELECT extract(hour FROM NOW() AT TIME ZONE 'America/Barbados')::int AS h"

_Q_FEEDBACK_ALERTED_TODAY = """
    SELECT 1 FROM send_guard_event
     WHERE event = %(event)s
       AND at > NOW() - interval '2 days'
       AND (at AT TIME ZONE 'America/Barbados')::date = (NOW() AT TIME ZONE 'America/Barbados')::date
     LIMIT 1
"""


def unanswered_feedback_events(tx, *, from_hour: Optional[int] = None) -> list[dict]:
    """The day's reminder about reports still `new` after 24 hours, as one
    alertable event, or nothing: before from_hour, when today's has already
    been recorded, or when every report has been handled."""
    from service.feedback.rewards import stale_new
    hour = FEEDBACK_ALERT_FROM_HOUR if from_hour is None else from_hour
    if tx.execute(_Q_BARBADOS_HOUR).fetchone()['h'] < hour:
        return []
    if tx.execute(_Q_FEEDBACK_ALERTED_TODAY, dict(event=FEEDBACK_ALERT_EVENT)).fetchone():
        return []
    reports = stale_new(tx)
    if not reports:
        return []
    return [dict(at=datetime.now(timezone.utc).isoformat(), channel='guard', event=FEEDBACK_ALERT_EVENT,
                 alert=True, detail=dict(reports=[dict(id=int(r['id']), category=str(r['category']),
                                                       age_hours=int(r['age_hours'])) for r in reports]))]


# ---------------------------------------------------------------------------
# support messages nobody has answered (TEC-2115)
# ---------------------------------------------------------------------------

SUPPORT_ALERT_EVENT = 'support_unanswered'


def unanswered_support_events(tx, *, from_hour: Optional[int] = None) -> list[dict]:
    """The day's reminder about support messages still open after 24 hours,
    as one alertable event, or nothing: before from_hour, when today's has
    already been recorded, or when every message has been dealt with."""
    from service.support_inbox.admin import stale_open
    hour = FEEDBACK_ALERT_FROM_HOUR if from_hour is None else from_hour
    if tx.execute(_Q_BARBADOS_HOUR).fetchone()['h'] < hour:
        return []
    if tx.execute(_Q_FEEDBACK_ALERTED_TODAY, dict(event=SUPPORT_ALERT_EVENT)).fetchone():
        return []
    messages = stale_open(tx)
    if not messages:
        return []
    return [dict(at=datetime.now(timezone.utc).isoformat(), channel='guard', event=SUPPORT_ALERT_EVENT,
                 alert=True, detail=dict(messages=[dict(id=int(m['id']), age_hours=int(m['age_hours']))
                                                   for m in messages]))]


_SUPPORT_SAVEPOINT = 'support_alert'


def _support_events_isolated(tx) -> list[dict]:
    """The support reminder for the tick: nothing at all, not even a read,
    while the support inbox is switched off; and in its own savepoint, so a
    failed read cannot break the halt sync and tallies in the same
    transaction."""
    from service.support_inbox import enabled
    if not enabled():
        return []
    tx.execute(f'SAVEPOINT {_SUPPORT_SAVEPOINT}')
    try:
        out = unanswered_support_events(tx)
    except Exception as e:  # noqa: BLE001 -- the rest of the tick goes on
        tx.execute(f'ROLLBACK TO SAVEPOINT {_SUPPORT_SAVEPOINT}')
        print(f'sendguard: support reminder skipped ({type(e).__name__})', flush=True)
        return []
    tx.execute(f'RELEASE SAVEPOINT {_SUPPORT_SAVEPOINT}')
    return out


# ---------------------------------------------------------------------------
# the owner's alert
# ---------------------------------------------------------------------------

FEEDBACK_ALERT_LISTED = 20


def describe(ev: dict) -> str:
    """One line per event, for the owner. Sentence case, British spelling,
    no em dashes, no exclamation marks."""
    name, channel = ev.get('event'), ev.get('channel') or 'email'
    kind, rule = ev.get('kind') or 'unknown', ev.get('rule') or ''
    detail = ev.get('detail') or {}
    if name == FEEDBACK_ALERT_EVENT:
        reports = detail.get('reports') or []
        n = len(reports)
        listed = '; '.join(f'report {r.get("id")} ({r.get("category")}, {r.get("age_hours")} hours)'
                           for r in reports[:FEEDBACK_ALERT_LISTED])
        if n > FEEDBACK_ALERT_LISTED:
            listed += f'; and {n - FEEDBACK_ALERT_LISTED} more'
        return (f'{n} member report{"s have" if n != 1 else " has"} had no answer for more than 24 hours: '
                f'{listed}. Mark each one fixed or not a fault on the System tab.')
    if name == SUPPORT_ALERT_EVENT:
        messages = detail.get('messages') or []
        n = len(messages)
        listed = '; '.join(f'message {m.get("id")} ({m.get("age_hours")} hours)'
                           for m in messages[:FEEDBACK_ALERT_LISTED])
        if n > FEEDBACK_ALERT_LISTED:
            listed += f'; and {n - FEEDBACK_ALERT_LISTED} more'
        return (f'{n} support message{"s have" if n != 1 else " has"} had no answer for more than 24 hours: '
                f'{listed}. Reply in Gmail, then mark each one handled or not for us on the Support tab.')
    if name == 'refused':
        return (f'The first {channel} of kind {kind} was refused today ({rule}). '
                'Later refusals of it today are counted but not emailed.')
    if name == 'halt':
        if detail.get('scope') == 'all' or ev.get('kind') is None:
            return (f'Every non-essential {channel} is halted ({detail.get("reason") or rule}). '
                    'Sign-in codes still go. Clear it with scripts/mail_guard_clear.py once the cause is fixed.')
        return (f'{channel.capitalize()} of kind {kind} is halted for everyone ({detail.get("reason") or rule}). '
                'Clear it with scripts/mail_guard_clear.py once the cause is fixed.')
    if name == 'essential_cap':
        return ('A sign-in or change-of-email code was refused: one address asked for more '
                'than 25 in 24 hours.')
    if name == 'dry_run_send':
        return f'A trial run tried to send {channel} of kind {kind}. It was stopped. Find the code that sends in a dry run.'
    if name == 'ceiling_shadow':
        return (f'The global {rule.replace("_", " ")} ceiling for {channel} was crossed during the trial week. '
                f'Nothing was stopped. The trial ends on {detail.get("shadow_until")}.')
    if name == 'shadow_ended':
        return 'The trial week has ended. The global ceilings now stop mail when crossed.'
    if name == 'bulk_window_ignored':
        return 'AHAVAH_SEND_GUARD_BULK_UNTIL is more than 24 hours ahead or unreadable, so it is ignored.'
    if name == 'redis_down':
        return 'Redis could not be reached. The guard used its in-process counters, which are per process.'
    if name == 'guard_unavailable':
        return 'The guard could not count at all, so it refused non-essential mail. Codes still go.'
    return f'{name} ({channel}, {kind}).'


def _alert_text(events: list[dict], *, last: bool) -> tuple[str, str]:
    n = len(events)
    subject = f'Ahavah mail guard: {n} alert{"s" if n != 1 else ""}'
    names = {e.get('event') for e in events}
    if names == {FEEDBACK_ALERT_EVENT}:
        subject = 'Ahavah: member reports with no answer'
    elif names == {SUPPORT_ALERT_EVENT}:
        subject = 'Ahavah: support messages with no answer'
    elif names == {FEEDBACK_ALERT_EVENT, SUPPORT_ALERT_EVENT}:
        subject = 'Ahavah: member reports and support messages with no answer'
    lines = [describe(e) for e in events]
    footer = ['', 'The stats route and the watchdog see every event. Runbook: docs/runbooks/mail-guard.md.']
    if last:
        footer.append('This is the last alert email today. The stats route and the watchdog still see every event.')
    html = ''.join(f'<p>{_esc(l)}</p>' for l in lines + footer if l)
    return subject, html


def _esc(s: str) -> str:
    from html import escape
    return escape(s)


def _send_alert(events: list[dict]) -> list[dict]:
    """Send the alert outside any transaction (the push sender opens its
    own, and the api connection lock is not re-entrant). Returns the
    failures to record."""
    from smtp import make_aws_smtp
    # The push shares the email's daily cap (review, 2 Nov 2026): without it
    # an event source that never stops pushed to the owner every minute.
    capped = guard.alerts_sent_today() >= guard.limit('alerts_per_day')
    last = guard.alerts_sent_today() + 1 >= guard.limit('alerts_per_day')
    subject, html = _alert_text(events, last=last)
    failures: list[dict] = []
    for to in alert_emails():
        try:
            make_aws_smtp().send(subject=subject, body=html, to_addr=to, kind=guard.GUARD_ALERT_KIND,
                                 raise_on_refusal=True, raise_on_failure=True,
                                 retries=1, backoff=ALERT_RETRY_BACKOFF)
        except guard.MailGuardRefused:
            failures.append(dict(channel='email', event='alert_capped', rule='alerts_per_day'))
        except Exception as e:  # noqa: BLE001 -- recorded, never raised: the tick goes on
            print(traceback.format_exc())
            failures.append(dict(channel='email', event='alert_failed', rule='send_failed',
                                 detail=dict(error=type(e).__name__)))
    pid = alert_person_id()
    if pid is not None and not capped:
        from service import notifications
        try:
            n = notifications._send_to_user_blocking(
                pid, dict(title='Ahavah mail guard', body=f'{len(events)} new. Check your email for the detail.',
                          url='/', tag='mail-guard'), kind=guard.GUARD_ALERT_KIND)
        except Exception as e:  # noqa: BLE001
            print(traceback.format_exc())
            n = 0
        if not n:
            failures.append(dict(channel='push', event='alert_failed', rule='no_live_subscription'))
    now = datetime.now(timezone.utc).isoformat()
    return [dict(f, at=now) for f in failures]


# ---------------------------------------------------------------------------
# the tick
# ---------------------------------------------------------------------------

def _shadow_ended(r) -> list[dict]:
    until = guard.shadow_until()
    if until is None or guard.global_mode() != 'enforce':
        return []
    if r.set(f'sg:shadow_ended:{until.isoformat()}', '1', nx=True):
        return [dict(at=datetime.now(timezone.utc).isoformat(), channel='guard', event='shadow_ended',
                     alert=True, detail=dict(shadow_until=until.isoformat()))]
    return []


_redis_outage_alerted = False


def _tick_without_redis(exc: BaseException) -> None:
    """Redis cannot be reached. Record what this process kept in memory and
    tell the owner once per outage, then let the tick fail so the heartbeat
    stays stale (review, 2 Nov 2026: the tick used to fail at its first
    Redis read, so the plan's redis_down alert was never stored or sent
    while Redis was down). The alert email passes the guard on its
    in-process counters; halts and tallies wait for Redis."""
    global _redis_outage_alerted
    local = guard.drain_local_events()
    if not _redis_outage_alerted:
        local.append(dict(at=datetime.now(timezone.utc).isoformat(), channel='guard', event='redis_down',
                          alert=True, detail=dict(error=type(exc).__name__, seen_by='sendguard')))
    try:
        with api_tx() as tx:
            insert_events(tx, local)
    except Exception:
        for ev in local:
            guard._local_events.append(json.dumps(ev))
        raise
    alertable = [e for e in local if e.get('alert')
                 and not (_redis_outage_alerted and e.get('event') == 'redis_down')]
    if alertable:
        _redis_outage_alerted = True
        failures = _send_alert(alertable)
        if failures:
            with api_tx() as tx:
                insert_events(tx, failures)


def tick() -> dict:
    """One pass. Raises on a failure part way, leaving the heartbeat stale."""
    global _redis_outage_alerted
    now = datetime.now(timezone.utc)
    r = guard._redis()
    try:
        raw = _read_redis_events(r)
    except Exception as exc:  # noqa: BLE001 -- recorded and alerted, then raised
        _tick_without_redis(exc)
        raise
    _redis_outage_alerted = False
    local = guard.drain_local_events()
    events = [json.loads(x) for x in raw] + local
    try:
        with api_tx() as tx:
            events += _shadow_ended(r)
            events += unanswered_feedback_events(tx)
            events += _support_events_isolated(tx)
            insert_events(tx, events)
            _flush_tallies(tx, r, now)
            _sync_halts(tx, r)
            tx.execute("DELETE FROM send_guard_event WHERE at < NOW() - make_interval(days => %(d)s)",
                       dict(d=EVENT_RETENTION_DAYS))
    except Exception:
        for ev in local:
            guard._local_events.append(json.dumps(ev))
        raise
    _trim_redis_events(r, len(raw))
    alertable = [e for e in events if e.get('alert')]
    if alertable:
        failures = _send_alert(alertable)
        if failures:
            with api_tx() as tx:
                insert_events(tx, failures)
    r.set(guard.heartbeat_key(), now.isoformat())
    return dict(events=len(events), alerts=len(alertable))
