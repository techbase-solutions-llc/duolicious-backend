"""GET /internal/send-stats: the send guard's figures for the outside
watchdog (send safeguards plan, 2 Nov 2026, task 4).

The watchdog (techbase-solutions-llc/mail-watchdog, a scheduled GitHub
Actions job) reads this every 30 minutes and alerts the owner on an open
halt, a trial run that tried to send, a capped sign-in code, a failed
alert, a stale heartbeat, Redis down, no live push subscription for the
alert member, a trial week past its date, or a push spike.

Auth: header X-Send-Stats must equal AHAVAH_SEND_STATS_SECRET, compared in
constant time. Unset, nothing opens it (fails closed, as
service/api/cron_auth.py does). It is read-only, X-Growth-Cron does not
open it, and its secret opens nothing else.

The answer carries no address: recipients are hashes in the events, and
none are listed here. It answers 200 when Redis is down, from Postgres, with
`redis: unreachable`.

Shape (the watchdog's README holds the same contract):

    redis                           'ok' or 'unreachable'
    heartbeat_age_seconds           seconds since the sendguard cron's last full tick, or null
    mode                            {per_person: 'enforce', global: 'shadow'|'enforce',
                                     global_shadow_until: 'YYYY-MM-DD' or null}
    open_halts                      [{channel, scope, kind, set_at, reason}]
    events_24h                      {event name: count}, every event type seen in 24 hours
    alert_failed_24h                count
    alert_member_push_subscriptions count of live subscriptions for AHAVAH_ALERT_PUSH_PERSON_ID
    email, push                     {'1h'|'24h'|'7d': {kind: {sent, refused, failed}}}; '1h' is the
                                    current and the previous clock hour (60 to 120 minutes)
    recent_events                   the last 20 events, without recipients
    outbox                          email_outbox rows by state
    switch_changes                  null until switch changes are recorded (plan task 5B)
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from flask import abort, request

from database import api_tx
from service.api.decorators import get
from smtp import guard

_WINDOWS = (('1h', timedelta(hours=1)), ('24h', timedelta(hours=24)), ('7d', timedelta(days=7)))
_OUTCOMES = ('sent', 'refused', 'failed')

_Q_TALLY = """
    SELECT hour, channel, kind, outcome, count FROM send_tally
     WHERE hour >= date_trunc('hour', NOW() - interval '7 days')
"""
_Q_HALTS = """
    SELECT channel, scope, kind, set_at, reason FROM send_guard_halt
     WHERE cleared_at IS NULL ORDER BY set_at
"""
_Q_EVENTS_24H = """
    SELECT event, count(*)::int AS n FROM send_guard_event
     WHERE at > NOW() - interval '24 hours' GROUP BY event
"""
_Q_RECENT = """
    SELECT at, channel, event, kind, rule, alert FROM send_guard_event ORDER BY id DESC LIMIT 20
"""
_Q_SUBSCRIPTIONS = "SELECT count(*)::int AS n FROM push_subscription WHERE person_id = %(p)s"
_Q_OUTBOX = "SELECT state, count(*)::int AS n FROM email_outbox GROUP BY state"


def _authorised() -> bool:
    secret = os.environ.get('AHAVAH_SEND_STATS_SECRET', '')
    if not secret:
        return False
    given = request.headers.get('X-Send-Stats', '')
    return bool(given) and hmac.compare_digest(given, secret)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _hour_start(now: datetime, hours_back: int) -> datetime:
    return (now - timedelta(hours=hours_back)).replace(minute=0, second=0, microsecond=0)


def _redis_reads(now: datetime):
    """(ok, heartbeat age, {(hour, channel, kind, outcome): count} for the
    current and previous hour)."""
    try:
        r = guard._redis()
        beat = r.get(guard.heartbeat_key())
        age = None
        if beat:
            age = max(0, int((now - datetime.fromisoformat(beat)).total_seconds()))
        recent = {}
        for back in (0, 1):
            start = _hour_start(now, back)
            for fld, n in (r.hgetall(f'sg:tally:{guard.utc_hour(start)}') or {}).items():
                channel, kind, outcome = fld.split('|', 2)
                recent[(start, channel, kind, outcome)] = int(n)
        return True, age, recent
    except Exception:  # noqa: BLE001 -- Redis down is a figure, not an error
        return False, None, {}


def _windows(rows: dict, now: datetime) -> dict:
    out = {ch: {w: {} for w, _ in _WINDOWS} for ch in ('email', 'push')}
    for (hour, channel, kind, outcome), n in rows.items():
        if channel not in out or outcome not in _OUTCOMES:
            continue
        for name, span in _WINDOWS:
            floor = _hour_start(now, 1) if name == '1h' else _hour_start(now - span, 0)
            if hour >= floor:
                k = out[channel][name].setdefault(kind, {o: 0 for o in _OUTCOMES})
                k[outcome] += n
    return out


@get('/internal/send-stats')
def get_send_stats():
    if not _authorised():
        abort(403)
    now = datetime.now(timezone.utc)
    redis_ok, heartbeat_age, recent = _redis_reads(now)
    from service.sendguard import alert_person_id
    pid = alert_person_id()
    with api_tx('read committed') as tx:
        rows = {(r['hour'], r['channel'], r['kind'], r['outcome']): int(r['count'])
                for r in tx.execute(_Q_TALLY).fetchall()}
        halts = [dict(r, set_at=_iso(r['set_at'])) for r in tx.execute(_Q_HALTS).fetchall()]
        events = {r['event']: r['n'] for r in tx.execute(_Q_EVENTS_24H).fetchall()}
        recent_events = [dict(r, at=_iso(r['at'])) for r in tx.execute(_Q_RECENT).fetchall()]
        subs = tx.execute(_Q_SUBSCRIPTIONS, dict(p=pid)).fetchone()['n'] if pid is not None else 0
        outbox = {r['state']: r['n'] for r in tx.execute(_Q_OUTBOX).fetchall()}
    # Redis holds this hour's and last hour's figures before the cron copies
    # them; the larger of the two is the truer.
    for key, n in recent.items():
        rows[key] = max(rows.get(key, 0), n)
    for state in ('queued', 'reserved', 'accepted', 'acceptance_unknown', 'failed', 'skipped'):
        outbox.setdefault(state, 0)
    until = guard.shadow_until()
    for name in ('dry_run_send', 'essential_cap', 'alert_failed'):
        events.setdefault(name, 0)
    return {
        'redis': 'ok' if redis_ok else 'unreachable',
        'heartbeat_age_seconds': heartbeat_age,
        'mode': {'per_person': 'enforce', 'global': guard.global_mode(now),
                 'global_shadow_until': until.isoformat() if until else None},
        'open_halts': halts,
        'events_24h': events,
        'alert_failed_24h': events.get('alert_failed', 0),
        'alert_member_push_subscriptions': subs,
        **_windows(rows, now),
        'recent_events': recent_events,
        'outbox': outbox,
        'switch_changes': None,
    }
