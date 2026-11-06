"""The send guard: one gate for every email and every web push.

Send safeguards plan, 2 Nov 2026 (docs/superpowers/plans/
2026-11-02-send-safeguards.md, task 1). For about a month a dormancy dry run
emailed "Your Ahavah profile is resting" to the same members every 10
minutes, straight through `aws_smtp.send`, outside the outbox, the send log
and every cap. Nothing counted it, nothing stopped it, nobody was told.

Every email ends in `Smtp.send` and every web push in
`service.notifications._send_one`, so the gate sits there and covers the
outbox drain, every direct sender and every manual script without editing
their callers.

How it decides
--------------
`check` increments every counter it tests in one Redis pipeline and decides
from the incremented values, so every attempt counts (whether it then
succeeds or fails) and 2 sends at once cannot both slip under a limit.
`record` notes the outcome for the tallies only.

- Per-person limits always enforce: the same kind to one address, a bulk
  kind once in 24 hours, every non-essential kind together.
- The global hourly and daily ceilings start in a trial week that ends on
  `AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL` (a Barbados date). Before it,
  crossing one alerts and stops nothing; on and after it, crossing one halts
  all non-essential mail. A missing or unreadable date means enforce.
- When 3 different people hit the same kind's limit within an hour, that kind
  halts for everyone until the owner clears it (`scripts/mail_guard_clear.py`
  or `POST /admin/system/mail-guard/clear`).
- Sign-in and change-of-email codes are never halted and never refused by a
  ceiling: only 25 per address in 24 hours, and every refusal alerts.
- Inside `no_send()` (every cron's dry run) any send raises
  `SendDuringDryRun`. The flag is a context variable, so it reaches threads
  started through `spawn` and `asyncio.to_thread`, and never another cron's
  asyncio task.

Nothing here touches Postgres: some callers of `send` already hold a
transaction and the api connection lock is not re-entrant. Events go to the
Redis list `sg:events`; the `sendguard` cron moves them to Postgres and sends
the owner one alert per tick (service/sendguard).

No address is stored anywhere: a recipient is the first 16 hex characters of
the SHA-256 of its lower-cased address.

If Redis cannot be reached the gate falls back to in-process counters with
the same limits (per process, so a little looser) and records `redis_down`.
If that fails too, non-essential mail is refused and codes are allowed.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# kinds
# ---------------------------------------------------------------------------

# Never halted, never refused by a global ceiling; capped per address only.
ESSENTIAL_KINDS = frozenset({'sign_in_code', 'change_email_code'})

# The gate's own alert to the owner: passes every halt and ceiling, capped
# at LIMITS['alerts_per_day'] a Barbados day.
GUARD_ALERT_KIND = 'guard_alert'

# "You have a new message on Ahavah" (service/cron/notifications, queued as
# outbox campaign 'message') can repeat for someone chatting a lot.
CHAT_EMAIL_KINDS = frozenset({'message'})
# One push per chat message (service/chat/messagestorage).
CHAT_PUSH_KINDS = frozenset({'chat_message'})

# Kinds sent to a list. A bulk kind reaches one address once in 24 hours,
# whatever the caller's `bulk` flag says. Each was read from its source:
BULK_KINDS = frozenset({
    'e1',                  # Spotlight announcement, emails/send_spotlight_announcement.py, send_spotlight_resend.py
    'e1_push_off',         # Spotlight announcement to push-off members, emails/send_spotlight_announcement_push_off.py
    'e2',                  # weekly community email, service/cron/communityweekly, emails/send_community_weekly.py
    'e3',                  # re-invite, emails/send_reinvite.py
    'e6',                  # notifications nudge, emails/send_notifications_nudge.py
    'spotlight_note',      # emails/send_spotlight_candidates_note.py
    'questions_launch',    # emails/questions_launch.py
    'likes_waiting',       # emails/likes_waiting_weekly.py (returnmail cron)
    'profile_views',       # emails/profile_views_weekly.py (returnmail cron)
    'one_photo',           # emails/one_photo_nudge.py (returnmail cron)
    'referral',            # service/cron/referralintro
    'beta_reengagement',   # service/cron/betareengagement via emails/reengagement.py
    'warm_leads_note_2026_10',  # emails/send_warm_leads_note.py
})
# service/cron/questionofweek queues a social post, not an email, so it has
# no kind here.

# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------

# One dict, with an environment override per limit
# (AHAVAH_SEND_GUARD_LIMIT_<NAME>), so tuning needs no code change.
LIMITS: dict[str, int] = {
    'email_per_kind': 3,               # same address, same kind, 24 hours
    'email_bulk_per_kind': 1,          # same address, same bulk kind, 24 hours
    'email_chat_per_kind': 10,         # same address, chat message email, 24 hours
    'email_owner_per_kind': 50,        # owner addresses, per kind, 24 hours
    'email_per_person_all': 12,        # same address, every non-essential kind, 24 hours
    'email_essential_per_person': 25,  # sign-in and change-of-email codes, 24 hours
    'email_global_hour': 300,          # every non-essential email, per hour
    'email_global_hour_bulk': 2000,    # the same inside AHAVAH_SEND_GUARD_BULK_UNTIL
    'email_global_day': 1500,          # every non-essential email, per Barbados day
    'push_per_kind': 6,                # same person, same kind, 24 hours
    'push_chat_per_kind': 100,         # same person, chat message push, 24 hours
    'push_per_person_all': 20,         # same person, every push but chat, 24 hours
    'push_global_hour': 1000,          # every push sent to a device, per hour
    'alerts_per_day': 20,              # the gate's own alert email, per Barbados day
    'kind_halt_people': 3,             # people over one kind's limit within an hour
}

DAY_SECONDS = 86400
_EVENTS_KEY = 'sg:events'
_EVENTS_MAX = 5000


def limit(name: str) -> int:
    raw = os.environ.get(f'AHAVAH_SEND_GUARD_LIMIT_{name.upper()}', '').strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return LIMITS[name]


def owner_addresses() -> frozenset[str]:
    raw = os.environ.get('AHAVAH_OWNER_ADDRESSES', 'admin@techbaseltd.com,harrigan.tennyson@gmail.com')
    return frozenset(a.strip().lower() for a in re.split(r'[,\s]+', raw) if a.strip())


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------

class GuardRefused(Exception):
    """A send the gate stopped."""

    def __init__(self, rule: str, kind: str, channel: str = 'email'):
        super().__init__(f'{channel} {kind} refused by the send guard ({rule})')
        self.rule = rule
        self.kind = kind
        self.channel = channel


class MailGuardRefused(GuardRefused):
    """A limit, halt or ceiling refused the send. `Smtp.send` raises it only
    for `raise_on_refusal=True` (the outbox drain); direct callers get None."""


class SendDuringDryRun(GuardRefused):
    """A send inside `no_send()`. Always raised: a dry run that tries to
    send is a bug, and it should fail where it happens."""


class SendFailed(Exception):
    """Every attempt of `Smtp.send(raise_on_failure=True)` failed."""


# ---------------------------------------------------------------------------
# the dry-run tripwire and threads
# ---------------------------------------------------------------------------

_no_send_var: contextvars.ContextVar[bool] = contextvars.ContextVar('send_guard_no_send', default=False)


@contextmanager
def no_send():
    """Every send inside raises SendDuringDryRun and records `dry_run_send`.
    A cron with a DRY_RUN wraps its whole `_once()` in this when the flag is
    on. It reaches threads started through `spawn` and `asyncio.to_thread`;
    a context variable set in one asyncio task never reaches another."""
    token = _no_send_var.set(True)
    try:
        yield
    finally:
        _no_send_var.reset(token)


def in_no_send() -> bool:
    return _no_send_var.get()


def dry_run(flag: bool):
    """`no_send()` when `flag` is on, otherwise nothing. Every cron with a
    DRY_RUN wraps its whole `_once()` in this."""
    from contextlib import nullcontext
    return no_send() if flag else nullcontext()


def spawn(target: Callable, *args, **kwargs) -> threading.Thread:
    """Start a daemon thread that carries the caller's context variables (the
    tripwire among them). A bare threading.Thread does not, so every module
    that sends starts its threads here (tests/test_send_rules_static.py)."""
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(target, *args), kwargs=kwargs, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# kinds from subjects and tags
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    text = re.sub(r'\d+', '#', (text or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def _hash12(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode('utf-8')).hexdigest()[:12]


def derive_kind(subject: Optional[str]) -> str:
    """A caller that names no kind gets one from its subject: lower-cased,
    each run of digits as one #, whitespace collapsed, hashed. "You have 3
    new likes" and "You have 12 new likes" are one kind."""
    return f'subj:{_hash12(subject or "")}'


def push_kind(payload: dict) -> str:
    """A push with no kind gets one from its tag, hashed as a subject is.
    Never from the title: titles name another member, which would give a
    fresh kind for each sender."""
    tag = (payload or {}).get('tag')
    if not tag:
        return 'push:untagged'
    return f'tag:{_hash12(str(tag))}'


def recipient_hash(addr: str) -> str:
    return hashlib.sha256((addr or '').strip().lower().encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------

# Barbados has no daylight saving: UTC-4 all year.
_BB = timezone(timedelta(hours=-4))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def bb_day(now: Optional[datetime] = None) -> str:
    return (now or _now()).astimezone(_BB).strftime('%Y%m%d')


def bb_hour(now: Optional[datetime] = None) -> str:
    return (now or _now()).astimezone(_BB).strftime('%Y%m%d%H')


def utc_hour(now: Optional[datetime] = None) -> str:
    return (now or _now()).astimezone(timezone.utc).strftime('%Y%m%d%H')


def shadow_until() -> Optional[date]:
    """The first Barbados day the global ceilings enforce, or None when the
    value is missing or unreadable (which enforces)."""
    raw = os.environ.get('AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL', '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def global_mode(now: Optional[datetime] = None) -> str:
    until = shadow_until()
    if until is None:
        return 'enforce'
    today = (now or _now()).astimezone(_BB).date()
    return 'shadow' if today < until else 'enforce'


def _parse_instant(raw: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_BB)
    return dt


def bulk_window(now: Optional[datetime] = None) -> tuple[bool, bool]:
    """(active, ignored). AHAVAH_SEND_GUARD_BULK_UNTIL raises the hourly
    ceiling until that time; a value more than 24 hours ahead is ignored."""
    raw = os.environ.get('AHAVAH_SEND_GUARD_BULK_UNTIL', '').strip()
    if not raw:
        return False, False
    until = _parse_instant(raw)
    now = now or _now()
    if until is None:
        return False, True
    if until <= now:
        return False, False
    if until - now > timedelta(hours=24):
        return False, True
    return True, False


# ---------------------------------------------------------------------------
# stores
# ---------------------------------------------------------------------------

_REDIS_HOST = os.environ.get('DUO_REDIS_HOST', 'redis')
_REDIS_PORT = int(os.environ.get('DUO_REDIS_PORT', 6379))
_redis_client: Any = None
_redis_lock = threading.Lock()


def _redis():
    """The Redis the API's rate limits already live in. Short timeouts: a
    slow Redis must not hold up a sign-in code."""
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                import redis
                _redis_client = redis.Redis(
                    host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True,
                    socket_connect_timeout=0.5, socket_timeout=0.5)
    return _redis_client


def set_redis(client) -> None:
    """Tests install a fakeredis client here."""
    global _redis_client
    _redis_client = client


class _RedisStore:
    def __init__(self, client):
        self.r = client

    def get_many(self, keys: list[str]) -> list[Optional[str]]:
        return list(self.r.mget(keys))

    def incr_many(self, items: list[tuple[str, int]]) -> list[int]:
        pipe = self.r.pipeline()
        for key, _ in items:
            pipe.incr(key)
        for key, _ in items:
            pipe.ttl(key)
        out = pipe.execute()
        counts = [int(c) for c in out[:len(items)]]
        ttls = out[len(items):]
        missing = [(k, ttl) for (k, ttl), t in zip(items, ttls) if t is None or int(t) < 0]
        if missing:
            pipe = self.r.pipeline()
            for key, ttl in missing:
                pipe.expire(key, ttl)
            pipe.execute()
        return counts

    def decr_many(self, keys: list[str]) -> None:
        pipe = self.r.pipeline()
        for key in keys:
            pipe.decr(key)
        pipe.execute()

    def set_nx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        return bool(self.r.set(key, value, nx=True, ex=ttl))

    def window_add(self, key: str, member: str, now: float, window: int) -> int:
        pipe = self.r.pipeline()
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, '-inf', now - window)
        pipe.zcard(key)
        pipe.expire(key, window * 2)
        return int(pipe.execute()[2])

    def hincr(self, key: str, fld: str, ttl: int) -> None:
        pipe = self.r.pipeline()
        pipe.hincrby(key, fld, 1)
        pipe.expire(key, ttl)
        pipe.execute()

    def push_events(self, payloads: list[str]) -> None:
        pipe = self.r.pipeline()
        for p in payloads:
            pipe.lpush(_EVENTS_KEY, p)
        pipe.ltrim(_EVENTS_KEY, 0, _EVENTS_MAX - 1)
        pipe.execute()


class _LocalStore:
    """The same operations in process memory, for when Redis is down."""

    def __init__(self):
        self._lock = threading.Lock()
        self._v: dict[str, tuple[Any, Optional[float]]] = {}

    def _get(self, key):
        item = self._v.get(key)
        if item is None:
            return None
        value, exp = item
        if exp is not None and exp <= time.time():
            del self._v[key]
            return None
        return value

    def get_many(self, keys):
        with self._lock:
            return [self._get(k) for k in keys]

    def incr_many(self, items):
        out = []
        with self._lock:
            for key, ttl in items:
                cur = self._get(key)
                if cur is None:
                    self._v[key] = (1, time.time() + ttl)
                    out.append(1)
                else:
                    exp = self._v[key][1]
                    self._v[key] = (int(cur) + 1, exp)
                    out.append(int(cur) + 1)
        return out

    def decr_many(self, keys):
        with self._lock:
            for key in keys:
                cur = self._get(key)
                if cur is not None:
                    self._v[key] = (int(cur) - 1, self._v[key][1])

    def set_nx(self, key, value, ttl=None):
        with self._lock:
            if self._get(key) is not None:
                return False
            self._v[key] = (value, time.time() + ttl if ttl else None)
            return True

    def window_add(self, key, member, now, window):
        with self._lock:
            members = self._get(key) or {}
            members = {m: t for m, t in members.items() if t > now - window}
            members[member] = now
            self._v[key] = (members, time.time() + window * 2)
            return len(members)

    def hincr(self, key, fld, ttl):
        pass  # tallies are best effort; the cron cannot read this process

    def push_events(self, payloads):
        for p in payloads:
            _local_events.append(p)

    def clear(self):
        with self._lock:
            self._v.clear()


_local_store = _LocalStore()
# Events recorded while Redis was down. Pushed to Redis when it answers
# again, and flushed to Postgres by the sendguard cron in its own process.
_local_events: deque = deque(maxlen=_EVENTS_MAX)
_last_redis_down = 0.0


def drain_local_events() -> list[dict]:
    out = []
    while True:
        try:
            out.append(json.loads(_local_events.popleft()))
        except IndexError:
            return out


def reset_local_state() -> None:
    """Tests: forget the in-process counters and events."""
    global _last_redis_down
    _local_store.clear()
    _local_events.clear()
    _last_redis_down = 0.0


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def _event(name: str, *, channel: str, kind: Optional[str] = None, rule: Optional[str] = None,
           recipient: Optional[str] = None, alert: bool = False, **detail) -> dict:
    return dict(at=_now().isoformat(), event=name, channel=channel, kind=kind, rule=rule,
                recipient=recipient, alert=alert, detail=detail)


def _note_redis_down(exc: BaseException) -> None:
    global _last_redis_down
    now = time.time()
    if now - _last_redis_down < 60:
        return
    _last_redis_down = now
    _local_events.append(json.dumps(_event('redis_down', channel='guard', alert=True,
                                           error=type(exc).__name__)))
    print(f'MAIL_GUARD {json.dumps(dict(event="redis_down", error=type(exc).__name__))}', flush=True)


def _publish(store, events: list[dict]) -> None:
    if not events:
        return
    payloads = [json.dumps(e) for e in events]
    try:
        store.push_events(payloads)
    except Exception:
        for p in payloads:
            _local_events.append(p)


def record_event(name: str, *, channel: str, kind: Optional[str] = None, alert: bool = False, **detail) -> None:
    """For the sendguard cron and the clear script: one event straight to the
    events list (or the local buffer if Redis is down)."""
    ev = _event(name, channel=channel, kind=kind, alert=alert, **detail)
    try:
        _RedisStore(_redis()).push_events([json.dumps(ev)])
    except Exception:
        _local_events.append(json.dumps(ev))


# ---------------------------------------------------------------------------
# halts
# ---------------------------------------------------------------------------

def halt_key(channel: str, kind: Optional[str]) -> str:
    prefix = 'sg:p:halt' if channel == 'push' else 'sg:halt'
    return f'{prefix}:all' if kind is None else f'{prefix}:kind:{kind}'


def _halt_value(reason: str) -> str:
    return json.dumps(dict(set_at=_now().isoformat(), reason=reason))


def set_halt(channel: str, kind: Optional[str], *, reason: str) -> bool:
    """Set a sticky halt. True when it was not set already."""
    return bool(_redis().set(halt_key(channel, kind), _halt_value(reason), nx=True))


def clear_halt_redis(channel: str, kind: Optional[str]) -> bool:
    """Redis side of clearing a halt. Use service.sendguard.clear_halt, which
    also closes the Postgres row: the cron puts back any halt still open
    there."""
    r = _redis()
    removed = r.delete(halt_key(channel, kind))
    if kind is not None:
        r.delete(_trip_key(channel, kind))
    return bool(removed)


def _trip_key(channel: str, kind: str) -> str:
    return f'sg:p:trip:{kind}' if channel == 'push' else f'sg:trip:{kind}'


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    allowed: bool
    rule: Optional[str] = None
    events: list = field(default_factory=list)


def _refusal_events(store, *, channel: str, kind: str, rule: str, recipient: str,
                    now: datetime, trip: bool) -> list[dict]:
    """The refusal event (alerting on the first refusal of the kind this
    Barbados day) and, when 3 people have now tripped the kind within an
    hour, the kind's halt."""
    prefix = 'sg:p:' if channel == 'push' else 'sg:'
    first = store.set_nx(f'{prefix}refused:{kind}:{bb_day(now)}', '1', 2 * DAY_SECONDS)
    events = [_event('refused', channel=channel, kind=kind, rule=rule, recipient=recipient, alert=first)]
    if trip:
        people = store.window_add(_trip_key(channel, kind), recipient, now.timestamp(), 3600)
        if people >= limit('kind_halt_people'):
            reason = f'{people} people over the {kind} limit within an hour'
            if store.set_nx(halt_key(channel, kind), _halt_value(reason)):
                events.append(_event('halt', channel=channel, kind=kind, rule='kind_halt', alert=True,
                                     scope='kind', reason=reason))
    return events


def _ceiling(store, *, channel: str, name: str, now: datetime) -> tuple[bool, list[dict]]:
    """A global ceiling crossed: (refuse, events). In the trial week it
    alerts once an hour per ceiling and refuses nothing; after it, it halts
    every non-essential send on the channel."""
    if global_mode(now) == 'shadow':
        prefix = 'sg:p:' if channel == 'push' else 'sg:'
        if store.set_nx(f'{prefix}ceil:{name}:{bb_hour(now)}', '1', 2 * 3600):
            return False, [_event('ceiling_shadow', channel=channel, rule=name, alert=True,
                                  shadow_until=str(shadow_until()))]
        return False, []
    reason = f'global {name} ceiling crossed'
    events = []
    if store.set_nx(halt_key(channel, None), _halt_value(reason)):
        events.append(_event('halt', channel=channel, rule=name, alert=True, scope='all', reason=reason))
    return True, events


def _decide_email(store, *, recipient: str, kind: str, bulk: bool, owner: bool, now: datetime) -> Decision:
    day = bb_day(now)
    if kind == GUARD_ALERT_KIND:
        n = store.incr_many([(f'sg:alerts:{day}', 2 * DAY_SECONDS)])[0]
        if n > limit('alerts_per_day'):
            return Decision(False, 'alerts_per_day')
        return Decision(True)

    if kind in ESSENTIAL_KINDS:
        n = store.incr_many([(f'sg:r:{recipient}:{kind}', DAY_SECONDS)])[0]
        if n > limit('email_essential_per_person'):
            return Decision(False, 'essential_cap', [_event(
                'essential_cap', channel='email', kind=kind, rule='essential_cap', recipient=recipient,
                alert=True)])
        return Decision(True)

    halts = store.get_many([halt_key('email', None), halt_key('email', kind)])
    if halts[0] is not None or halts[1] is not None:
        rule = 'halt_all' if halts[0] is not None else 'halt_kind'
        return Decision(False, rule, [_event('refused', channel='email', kind=kind, rule=rule,
                                             recipient=recipient)])

    bulk = bulk or kind in BULK_KINDS
    all_key = f'sg:r:{recipient}:all'
    global_keys = [f'sg:g:mail:{bb_hour(now)}', f'sg:g:mail:day:{day}']
    items = [(f'sg:r:{recipient}:{kind}', DAY_SECONDS)]
    if not owner:
        items.append((all_key, DAY_SECONDS))
    items += [(global_keys[0], 2 * DAY_SECONDS),
              (global_keys[1], 35 * DAY_SECONDS),
              (f'sg:k:{kind}:{day}', 35 * DAY_SECONDS)]
    counts = store.incr_many(items)
    per_kind = counts[0]
    per_all = None if owner else counts[1]
    g_hour, g_day = counts[-3], counts[-2]

    if owner:
        kind_limit, rule = limit('email_owner_per_kind'), 'owner_per_kind'
    elif bulk:
        kind_limit, rule = limit('email_bulk_per_kind'), 'bulk_repeat'
    elif kind in CHAT_EMAIL_KINDS:
        kind_limit, rule = limit('email_chat_per_kind'), 'chat_per_kind'
    else:
        kind_limit, rule = limit('email_per_kind'), 'per_kind'
    # A copy a per-person rule refuses is never sent, so it gives back what
    # it took from the person's total and the global ceilings: one person's
    # contained loop must not use up their other mail for the day, or tip
    # every member's mail into a global halt (review, 2 Nov 2026). Only the
    # counter of the rule that refused keeps counting the attempts.
    if per_kind > kind_limit:
        store.decr_many(([] if owner else [all_key]) + global_keys)
        return Decision(False, rule, _refusal_events(
            store, channel='email', kind=kind, rule=rule, recipient=recipient, now=now, trip=True))
    if per_all is not None and per_all > limit('email_per_person_all'):
        store.decr_many(global_keys)
        return Decision(False, 'per_person_all', _refusal_events(
            store, channel='email', kind=kind, rule='per_person_all', recipient=recipient, now=now,
            trip=False))

    events: list[dict] = []
    active, ignored = bulk_window(now)
    if ignored and store.set_nx(f'sg:bulkwarn:{day}', '1', 2 * DAY_SECONDS):
        events.append(_event('bulk_window_ignored', channel='email', alert=True,
                             value=os.environ.get('AHAVAH_SEND_GUARD_BULK_UNTIL', '')))
    hour_limit = limit('email_global_hour_bulk') if active else limit('email_global_hour')
    for name, count, lim in (('global_hour', g_hour, hour_limit),
                             ('global_day', g_day, limit('email_global_day'))):
        if count > lim:
            refuse, ev = _ceiling(store, channel='email', name=name, now=now)
            events += ev
            if refuse:
                events.append(_event('refused', channel='email', kind=kind, rule=name, recipient=recipient))
                return Decision(False, name, events)
            break
    return Decision(True, None, events)


def _decide_push_person(store, *, person: str, kind: str, now: datetime) -> Decision:
    if kind == GUARD_ALERT_KIND:
        return Decision(True)
    halts = store.get_many([halt_key('push', None), halt_key('push', kind)])
    if halts[0] is not None or halts[1] is not None:
        rule = 'halt_all' if halts[0] is not None else 'halt_kind'
        return Decision(False, rule, [_event('refused', channel='push', kind=kind, rule=rule,
                                             recipient=person)])
    chat = kind in CHAT_PUSH_KINDS
    items = [(f'sg:p:r:{person}:{kind}', DAY_SECONDS)]
    if not chat:
        items.append((f'sg:p:r:{person}:all', DAY_SECONDS))
    counts = store.incr_many(items)
    kind_limit = limit('push_chat_per_kind') if chat else limit('push_per_kind')
    if counts[0] > kind_limit:
        rule = 'chat_per_kind' if chat else 'per_kind'
        if not chat:
            store.decr_many([items[1][0]])  # a refused push takes nothing from the person's total
        return Decision(False, rule, _refusal_events(
            store, channel='push', kind=kind, rule=rule, recipient=person, now=now, trip=True))
    if not chat and counts[1] > limit('push_per_person_all'):
        return Decision(False, 'per_person_all', _refusal_events(
            store, channel='push', kind=kind, rule='per_person_all', recipient=person, now=now, trip=False))
    return Decision(True)


def _decide_push_send(store, *, kind: str, now: datetime) -> Decision:
    if kind == GUARD_ALERT_KIND:
        return Decision(True)
    n = store.incr_many([(f'sg:p:g:{bb_hour(now)}', 2 * DAY_SECONDS)])[0]
    if n > limit('push_global_hour'):
        refuse, events = _ceiling(store, channel='push', name='global_hour', now=now)
        if refuse:
            events.append(_event('refused', channel='push', kind=kind, rule='global_hour'))
            return Decision(False, 'global_hour', events)
        return Decision(True, None, events)
    return Decision(True)


def _run(decide: Callable[[Any], Decision], *, essential: bool, channel: str, kind: str) -> Decision:
    """Decide on Redis; on any Redis error, on the in-process store; if that
    fails too, refuse non-essential and allow essential (fail closed)."""
    try:
        store = _RedisStore(_redis())
        decision = decide(store)
        if _local_events:
            # Redis answers again: hand it what was recorded while it did not.
            pending = []
            while _local_events:
                try:
                    pending.append(_local_events.popleft())
                except IndexError:
                    break
            try:
                store.push_events(pending)
            except Exception:
                _local_events.extend(pending)
        _publish(store, decision.events)
        return decision
    except Exception as exc:  # noqa: BLE001 -- any Redis fault falls back
        _note_redis_down(exc)
    try:
        decision = decide(_local_store)
        _publish(_local_store, decision.events)
        return decision
    except Exception as exc:  # noqa: BLE001
        print(f'MAIL_GUARD {json.dumps(dict(event="guard_unavailable", error=type(exc).__name__))}', flush=True)
        _local_events.append(json.dumps(_event('guard_unavailable', channel=channel, kind=kind, alert=True,
                                               error=type(exc).__name__)))
        if essential:
            return Decision(True)
        return Decision(False, 'guard_unavailable')


def _log_refusal(channel: str, kind: str, rule: str, recipient: str) -> None:
    print('MAIL_GUARD ' + json.dumps(dict(event='refused', channel=channel, kind=kind, rule=rule,
                                          recipient=recipient)), flush=True)


def tripwire(channel: str, kind: str, recipient: Optional[str] = None) -> None:
    """Raise SendDuringDryRun (and record it) inside `no_send()`."""
    _tripwire(channel, kind, recipient)


def _tripwire(channel: str, kind: str, recipient: Optional[str]) -> None:
    if not in_no_send():
        return
    ev = _event('dry_run_send', channel=channel, kind=kind, rule='dry_run', recipient=recipient, alert=True)
    try:
        _publish(_RedisStore(_redis()), [ev])
    except Exception:
        _local_events.append(json.dumps(ev))
    print('MAIL_GUARD ' + json.dumps(dict(event='dry_run_send', channel=channel, kind=kind)), flush=True)
    raise SendDuringDryRun('dry_run', kind, channel)


# ---------------------------------------------------------------------------
# the public gate
# ---------------------------------------------------------------------------

def check(to_addr: str, kind: str, *, bulk: bool = False) -> None:
    """Before an email. Raises SendDuringDryRun inside `no_send()` and
    MailGuardRefused when a limit, halt or ceiling refuses it."""
    recipient = recipient_hash(to_addr)
    _tripwire('email', kind, recipient)
    owner = (to_addr or '').strip().lower() in owner_addresses()
    now = _now()
    decision = _run(lambda s: _decide_email(s, recipient=recipient, kind=kind, bulk=bulk, owner=owner,
                                            now=now),
                    essential=kind in ESSENTIAL_KINDS or kind == GUARD_ALERT_KIND, channel='email', kind=kind)
    if not decision.allowed:
        _tally('email', kind, 'refused')
        _log_refusal('email', kind, decision.rule or '', recipient)
        raise MailGuardRefused(decision.rule or 'refused', kind, 'email')


def record(to_addr: str, kind: str, outcome: str) -> None:
    """After an email: 'sent' or 'failed', for the tallies. Never raises."""
    _tally('email', kind, outcome)


def check_push(person_id: int, kind: str) -> None:
    """Before pushing to one member (once, whatever their device count)."""
    person = f'p{person_id}'
    _tripwire('push', kind, person)
    now = _now()
    decision = _run(lambda s: _decide_push_person(s, person=person, kind=kind, now=now),
                    essential=kind == GUARD_ALERT_KIND, channel='push', kind=kind)
    if not decision.allowed:
        _tally('push', kind, 'refused')
        _log_refusal('push', kind, decision.rule or '', person)
        raise MailGuardRefused(decision.rule or 'refused', kind, 'push')


def check_push_send(kind: str) -> None:
    """Before each device send in `_send_one`: the tripwire and the global
    push ceiling, so a script that calls `_send_one` directly is counted."""
    _tripwire('push', kind, None)
    now = _now()
    decision = _run(lambda s: _decide_push_send(s, kind=kind, now=now),
                    essential=kind == GUARD_ALERT_KIND, channel='push', kind=kind)
    if not decision.allowed:
        _tally('push', kind, 'refused')
        _log_refusal('push', kind, decision.rule or '', '')
        raise MailGuardRefused(decision.rule or 'refused', kind, 'push')


def record_push(kind: str, outcome: str) -> None:
    _tally('push', kind, outcome)


def _tally(channel: str, kind: str, outcome: str) -> None:
    try:
        _RedisStore(_redis()).hincr(f'sg:tally:{utc_hour()}', f'{channel}|{kind}|{outcome}', 35 * DAY_SECONDS)
    except Exception:
        pass


def alerts_sent_today() -> int:
    try:
        return int(_redis().get(f'sg:alerts:{bb_day()}') or 0)
    except Exception:
        return 0


def heartbeat_key() -> str:
    return 'sg:heartbeat'


def iter_halts(client) -> Iterable[tuple[str, Optional[str], str]]:
    """Every halt in Redis as (channel, kind or None, raw value)."""
    for pattern, channel in (('sg:halt:*', 'email'), ('sg:p:halt:*', 'push')):
        for key in client.scan_iter(match=pattern):
            rest = key.split(':halt:', 1)[1]
            kind = None if rest == 'all' else rest[len('kind:'):]
            value = client.get(key)
            if value is not None:
                yield channel, kind, value
