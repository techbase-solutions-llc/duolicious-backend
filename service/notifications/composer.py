"""The push composer on the Growth tab (TEC-2182; plan
docs/plans/2026-11-19-push-composer.md).

An admin writes one push (a draft), counts its audience, sends it to their
own devices (the test, required), dry-runs it, then sends it now or at a
set time, in Barbados time or at that clock time in each member's own zone.

THE ROW. push_composer_send is the draft and then the send. Its text, url
and filters change only while it is a draft (state draft or tested), and
any change clears the test. Pressing Send freezes it: the idempotency key
is the draft id and a hash of its content, so a second press or a retried
request returns the first send. One send row is one pass over its
audience, never a loop.

THE AUDIENCE is frozen at the send's first pass into push_composer_recipient,
one row per member, and every member ends in one counted state: sent, held
(quiet hours or a rest period; tried again next tick), capped, failed,
expired (still held when the hold window closed), released (a cancel) or
skipped (left the audience after the freeze: toggle off, unsubscribed,
deleted). Nobody is dropped silently.

THE SEND. Each pass claims push_send_log (person, 'composer',
'<send id>:pending') before the push, sends after the commit, moves the
row to '<send id>' once a device took it and gives the claim back when
none did, as service/spotlight/prompts.py does. A member whose push
reached no device is tried once more on the next tick, then counted
failed. Every push goes through send_to_user_counted with
event_kind='announcement' and kind='composer:<send id>', never notify(),
which would fall back to email, so the send guard's own per member and
hourly limits apply underneath.

THE CAPS. An audience over PUSH_CAP (500, the Spotlight cap) or over
AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE when that is set lower is refused. A
member gets at most 1 composer push in 72 hours and 2 in 7 days; past that
they are counted capped. At most 2 composer sends are scheduled on one
Barbados day, and at most 1,000 composer pushes go in one Barbados day.

THE SWITCH. AHAVAH_PUSH_COMPOSER_ENABLED, default off. While it is off the
cron tick sends nothing and the send, cancel and list routes answer 404.
Drafts, the audience count, the dry run and the test send still work.

Always left out, by SQL the admin cannot change: staff, testers (except in
a testers-only send, which reaches testers only), members with deletion
requested or deactivated by an admin, excluded and suppressed addresses,
campaign unsubscribes and members with news and suggestions off.
"""
from __future__ import annotations

import hashlib
import json
import os
import traceback
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from emails.base import suppressed_sql_pattern
from service.campaigns import suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.switches import enabled
from service.growth.queries import _excluded
from service.man_woman import staff_sql
from service.questions.pushes import quiet, zone
from service.questions.schedule import resting
from service.spotlight import restdays
from service.testers import tester_sql

SWITCH = 'push_composer'
CAMPAIGN = 'composer'
TEST_KIND = 'composer_test'
TAP_SRC = 'apush'

PUSH_CAP = 500
TITLE_MAX = 50
BODY_MAX = 120
TEST_VALID = timedelta(hours=24)
HOLD_WINDOW = timedelta(hours=48)
MEMBER_SHORT = (timedelta(hours=72), 1)
MEMBER_LONG = (timedelta(days=7), 2)
DAY_SENDS = 2
DAY_PUSHES = 1000
# THE PASS LEASE. A pass writes a fresh pass_token on the send row and
# renews pass_heartbeat_at before every push; a pass that finds the lease
# renewed in the last LEASE_STALE_MINUTES sends nothing. A claim (a
# 'claimed' recipient, a ':pending' push_send_log row) is taken over only
# when it is older than that and the new pass holds the lease, and a pass
# that finds it has lost the lease stops before its next push. Every push
# ends within PUSH_TIMEOUT_SECONDS a device (service/notifications), so a
# live pass renews far more often than this.
LEASE_STALE_MINUTES = 15
PENDING_RETRY_MINUTES = LEASE_STALE_MINUTES

# Transaction-scoped advisory locks: the 2-sends-a-day count and each
# pass's per-member cap read and claims run one at a time.
_LOCK_SENDS = 'push_composer:sends'
_LOCK_CLAIMS = 'push_composer:claims'


def _xact_lock(tx, key: str) -> None:
    tx.execute("SELECT pg_advisory_xact_lock(hashtext(%(k)s))", dict(k=key))
# A push that reached no device is tried this many times in all.
MAX_ATTEMPTS = 2

BARBADOS = restdays.BARBADOS
# The earliest and latest zones on earth, for a member_local slot's range.
_EARLIEST = timezone(timedelta(hours=14))
_LATEST = timezone(timedelta(hours=-12))

OPEN_STATES = ('draft', 'tested')
LIVE_STATES = ('scheduled', 'sending')


class Refused(Exception):
    """A request the composer will not carry out. `reason` is a stable code
    the admin turns into words; `status` is the HTTP status."""

    def __init__(self, reason: str, status: int = 409, **detail):
        super().__init__(reason)
        self.reason, self.status, self.detail = reason, status, detail

    def answer(self) -> tuple[dict, int]:
        return dict(error=self.reason, **self.detail), self.status


def switch_on() -> bool:
    return enabled(SWITCH)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def max_audience() -> int:
    """PUSH_CAP, or AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE when that is set to a
    lower whole number above 0. Anything else reads as unset."""
    raw = os.environ.get('AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE', '').strip()
    try:
        n = int(raw)
    except ValueError:
        return PUSH_CAP
    return n if 0 < n < PUSH_CAP else PUSH_CAP


# ---------------------------------------------------------------------------
# Tap targets
# ---------------------------------------------------------------------------

def _events_list_on() -> bool:
    from service.events import surface_on
    return surface_on('events_list')


def _hosting_on() -> bool:
    from service.events import surface_on
    return surface_on('events_hosting')


def _together_on() -> bool:
    from service.tools import live
    return live()


# Checked against ahavah-web origin/master 9953a4d on 22 Nov 2026 (see the
# plan's "API contract for the admin card"). /chat and /likes are not pages
# there: the conversation list is /inbox and the likes are a tab of
# /matches. /your-ahavah is the light sign-in for people with no account,
# so it is not a member's page. /verify is the verification page. Each
# value is the label the admin shows and, where the page is behind a
# switch, the check that it is open.
URLS: dict[str, tuple[str, Any]] = {
    '/discover': ('Discover', None),
    '/matches': ('Matches', None),
    '/matches?tab=likes': ('Likes', None),
    '/inbox': ('Inbox', None),
    '/profile': ('Your profile', None),
    '/verify': ('Get verified', None),
    '/settings/notifications': ('Notification settings', None),
    '/settings/privacy': ('Privacy settings', None),
    '/events': ('Gatherings', _events_list_on),
    '/host': ('Host a gathering', _hosting_on),
    '/together': ('Together', _together_on),
}


def url_options() -> list[dict]:
    return [dict(url=u, label=label, available=gate is None or bool(gate()))
            for u, (label, gate) in URLS.items()]


def tap_url(url: str, send_id: str) -> str:
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}src={TAP_SRC}&send={send_id}'


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

_LINE_BREAKS = ('\n', '\r', ' ', ' ', '\x0b', '\x0c', '\x85')
_DASHES = ('—', '–')   # em and en dash


def check_text(title: Any, body: Any) -> tuple[str, str]:
    """The title and body as they will be sent, or Refused(400). Whole
    characters are counted (code points). The copy check: no em or en
    dash anywhere and no exclamation mark (the house style)."""
    problems: list[dict] = []
    out = []
    for field, value, most in (('title', title, TITLE_MAX), ('body', body, BODY_MAX)):
        if not isinstance(value, str) or not value.strip():
            problems.append(dict(field=field, problem='required'))
            out.append('')
            continue
        v = value.strip()
        if any(c in v for c in _LINE_BREAKS):
            problems.append(dict(field=field, problem='line_break'))
        if len(v) > most:
            problems.append(dict(field=field, problem='too_long', most=most, length=len(v)))
        if any(c in v for c in _DASHES):
            problems.append(dict(field=field, problem='dash'))
        if '!' in v:
            problems.append(dict(field=field, problem='exclamation'))
        out.append(v)
    if problems:
        raise Refused('invalid_text', 400, problems=problems)
    return out[0], out[1]


def check_url(url: Any) -> str:
    if not isinstance(url, str) or url not in URLS:
        raise Refused('invalid_url', 400)
    gate = URLS[url][1]
    if gate is not None and not gate():
        raise Refused('url_not_open', 400)
    return url


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

TIERS = ('none', 'bronze', 'silver', 'gold')
GENDERS = ('Man', 'Woman')
ONLINE_DAYS = (7, 14, 30)
FILTER_KEYS = ('gender', 'countries', 'regions', 'online_within_days', 'offline_for_days',
               'joined_within_days', 'has_photo', 'tiers', 'premium', 'spotlight')


def _bool(v) -> bool:
    if not isinstance(v, bool):
        raise Refused('invalid_filters', 400)
    return v


def clean_filters(raw: Any) -> dict:
    """The filters a draft keeps, or Refused(400). An absent or null key is
    no filter; an unknown key is refused, so a typo never widens a send."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise Refused('invalid_filters', 400)
    unknown = set(raw) - set(FILTER_KEYS)
    if unknown:
        raise Refused('invalid_filters', 400, unknown=sorted(unknown))
    f: dict = {}
    for k, v in raw.items():
        if v is None:
            continue
        if k == 'gender':
            if v not in GENDERS:
                raise Refused('invalid_filters', 400)
            f[k] = v
        elif k == 'countries':
            if (not isinstance(v, list) or not v or len(v) > 50
                    or not all(isinstance(c, str) and len(c) == 2 and c.isalpha() for c in v)):
                raise Refused('invalid_filters', 400)
            f[k] = sorted({c.upper() for c in v})
        elif k == 'regions':
            if (not isinstance(v, list) or not v or len(v) > 50
                    or not all(isinstance(r, str) and 0 < len(r.strip()) <= 100 for r in v)):
                raise Refused('invalid_filters', 400)
            f[k] = sorted({r.strip().lower() for r in v})
        elif k in ('online_within_days', 'offline_for_days'):
            if type(v) is not int or v not in ONLINE_DAYS:
                raise Refused('invalid_filters', 400)
            f[k] = v
        elif k == 'joined_within_days':
            if type(v) is not int or not 1 <= v <= 365:
                raise Refused('invalid_filters', 400)
            f[k] = v
        elif k == 'tiers':
            if not isinstance(v, list) or not v or not all(t in TIERS for t in v):
                raise Refused('invalid_filters', 400)
            f[k] = sorted(set(v))
        else:
            f[k] = _bool(v)
    if 'online_within_days' in f and 'offline_for_days' in f:
        raise Refused('invalid_filters', 400, conflict=['online_within_days', 'offline_for_days'])
    return f


def _premium_sql(a: str) -> str:
    """Premium as the app reads it (service/entitlements has_entitlement):
    'premium' in person.entitlements and the expiry not passed. Not
    has_gold, which nothing in the Ahavah app grants."""
    return (f"('premium' = ANY(COALESCE({a}.entitlements, ARRAY[]::text[])) "
            f"AND ({a}.subscription_expires_at IS NULL OR {a}.subscription_expires_at > NOW()))")


def _photo_sql(a: str) -> str:
    """An approved photo, as the deck requires (service/search/sql)."""
    return (f"EXISTS (SELECT 1 FROM photo ph WHERE ph.person_id = {a}.id "
            f"AND ph.moderation_status = 'approved')")


def filters_sql(f: dict, a: str = 'p') -> tuple[str, dict]:
    """The AND-ed SQL for a draft's filters, and its binds."""
    parts: list[str] = []
    binds: dict = {}
    if 'gender' in f:
        parts.append(f"{a}.gender_id = (SELECT id FROM gender WHERE name = %(f_gender)s)")
        binds['f_gender'] = f['gender']
    if 'countries' in f:
        parts.append(f"upper({a}.country) = ANY(%(f_countries)s)")
        binds['f_countries'] = f['countries']
    if 'regions' in f:
        parts.append(f"lower(trim({a}.region)) = ANY(%(f_regions)s)")
        binds['f_regions'] = f['regions']
    if 'online_within_days' in f:
        parts.append(f"{a}.last_online_time > NOW() - make_interval(days => %(f_online)s)")
        binds['f_online'] = f['online_within_days']
    if 'offline_for_days' in f:
        parts.append(f"{a}.last_online_time <= NOW() - make_interval(days => %(f_offline)s)")
        binds['f_offline'] = f['offline_for_days']
    if 'joined_within_days' in f:
        parts.append(f"{a}.sign_up_time > NOW() - make_interval(days => %(f_joined)s)")
        binds['f_joined'] = f['joined_within_days']
    if 'has_photo' in f:
        parts.append(_photo_sql(a) if f['has_photo'] else f"NOT {_photo_sql(a)}")
    if 'tiers' in f:
        parts.append(f"{a}.ahavah_verification_tier::text = ANY(%(f_tiers)s)")
        binds['f_tiers'] = f['tiers']
    if 'premium' in f:
        parts.append(_premium_sql(a) if f['premium'] else f"NOT {_premium_sql(a)}")
    if 'spotlight' in f:
        parts.append(f"{a}.spotlight_opt_in" if f['spotlight'] else f"NOT {a}.spotlight_opt_in")
    return (' AND '.join(parts) or 'TRUE'), binds


# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------

def base_rules_sql(a: str = 'p') -> str:
    """The fixed exclusions. Binds %(ex)s, %(sup)s and %(testers_only)s.
    A testers-only send reaches testers only; any other reaches no tester."""
    return f"""{a}.activated AND {a}.deletion_requested_at IS NULL
       AND {a}.admin_deactivated_at IS NULL
       AND NOT {staff_sql(a)}
       AND ({tester_sql(a)}) = %(testers_only)s
       AND lower({a}.email) <> ALL(%(ex)s)
       AND NOT ({suppressed_predicate_sql(f'{a}.email')})
       AND NOT ({unsubscribed_predicate_sql('campaigns', f'{a}.id')})
       AND COALESCE((SELECT np.push_announcements FROM notification_preference np
                      WHERE np.person_id = {a}.id), TRUE)
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {a}.id)"""


def _tz(a: str = 'p') -> str:
    return f"""(SELECT ps.tz FROM push_subscription ps
                 WHERE ps.person_id = {a}.id AND ps.tz IS NOT NULL
                 ORDER BY ps.updated_at DESC LIMIT 1)"""


def _base_binds(testers_only: bool) -> dict:
    # Testers are kept apart by role here (tester_sql), so the address list
    # leaves them in: _excluded() would otherwise drop them from a
    # testers-only send too.
    return dict(ex=_excluded(testers=False), sup=suppressed_sql_pattern(), testers_only=testers_only)


def audience(tx, filters: dict, testers_only: bool) -> list[dict]:
    """Every member a send with these filters reaches now: id, newest known
    zone and country. Counts are all a route ever returns."""
    where, binds = filters_sql(filters)
    q = f"""SELECT p.id AS person_id, {_tz('p')} AS tz, upper(p.country) AS country
              FROM person p
             WHERE {base_rules_sql('p')} AND {where}
             ORDER BY p.id"""
    return [dict(r) for r in tx.execute(q, dict(_base_binds(testers_only), **binds)).fetchall()]


def _still_in(tx, person_ids: list[int], testers_only: bool) -> set[int]:
    """Of these members, those the fixed exclusions still let through."""
    if not person_ids:
        return set()
    q = f"SELECT p.id FROM person p WHERE p.id = ANY(%(ids)s) AND {base_rules_sql('p')}"
    return {r['id'] for r in tx.execute(q, dict(_base_binds(testers_only), ids=person_ids)).fetchall()}


def _quiet_at(tz: Optional[str], now: datetime) -> bool:
    return quiet(now.astimezone(zone(tz)))


def audience_summary(tx, filters: dict, testers_only: bool, now: Optional[datetime] = None) -> dict:
    """POST /admin/growth/push/audience: how many, how many are held right
    now and why, and how many per country. Never a name."""
    now = now or _now()
    rows = audience(tx, filters, testers_only)
    rest = resting(now)
    quiet_n = 0 if rest else sum(1 for r in rows if _quiet_at(r['tz'], now))
    by: dict[str, int] = {}
    for r in rows:
        key = r['country'] or 'unknown'
        by[key] = by.get(key, 0) + 1
    cap = max_audience()
    return dict(count=len(rows), held_now=dict(quiet=quiet_n, resting=len(rows) if rest else 0),
                by_country=[dict(country=c, count=n) for c, n in sorted(by.items(), key=lambda x: (-x[1], x[0]))],
                max_audience=cap, over_cap=len(rows) > cap)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def content_hash(title: str, body: str, url: str, filters: dict, testers_only: bool) -> str:
    blob = json.dumps(dict(t=title, b=body, u=url, f=filters, x=bool(testers_only)),
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:32]


def filters_hash(filters: dict) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def clean_draft(body: dict) -> dict:
    """The draft's fields from a request body, or Refused(400)."""
    title, text = check_text(body.get('title'), body.get('body'))
    url = check_url(body.get('url'))
    filters = clean_filters(body.get('filters'))
    testers_only = body.get('testers_only', False)
    if not isinstance(testers_only, bool):
        raise Refused('invalid_testers_only', 400)
    if testers_only and filters:
        # A testers-only send is a check on testers' devices; a filter on it
        # is a sign that a member send was meant (plan, Tester test send).
        raise Refused('testers_only_with_filters', 400)
    return dict(title=title, body=text, url=url, filters=filters, testers_only=testers_only)


_COLS = """id::text AS id, title, body, url, filters, testers_only, content_hash, idempotency_key,
           state, scheduled_for, mode, local_at, hold_until, test_delivered_at, tested_hash,
           test_result, halt_reason, requested_when, created_at, updated_at, started_at, finished_at, cancelled_at,
           audience, sent, held, capped, failed, expired, released, skipped"""


def create_draft(tx, fields: dict, created_by: Optional[str]) -> dict:
    h = content_hash(**fields)
    return dict(tx.execute(
        f"""INSERT INTO push_composer_send (title, body, url, filters, testers_only, content_hash, created_by)
            VALUES (%(title)s, %(body)s, %(url)s, %(filters)s::jsonb, %(testers_only)s, %(h)s, %(by)s)
            RETURNING {_COLS}""",
        dict(fields, filters=json.dumps(fields['filters']), h=h, by=created_by)).fetchone())


def get(tx, send_id: str, *, lock: bool = False) -> Optional[dict]:
    row = tx.execute(f"SELECT {_COLS} FROM push_composer_send WHERE id = %(i)s::uuid"
                     + (' FOR UPDATE' if lock else ''), dict(i=send_id)).fetchone()
    return dict(row) if row else None


def update_draft(tx, send_id: str, fields: dict) -> dict:
    """A change to an open draft. Any change clears the test."""
    row = get(tx, send_id, lock=True)
    if row is None:
        raise Refused('not_found', 404)
    if row['state'] not in OPEN_STATES:
        raise Refused('not_a_draft')
    h = content_hash(**fields)
    if h == row['content_hash']:
        return row
    return dict(tx.execute(
        f"""UPDATE push_composer_send
               SET title = %(title)s, body = %(body)s, url = %(url)s, filters = %(filters)s::jsonb,
                   testers_only = %(testers_only)s, content_hash = %(h)s, state = 'draft',
                   test_delivered_at = NULL, tested_hash = NULL, test_result = NULL, updated_at = NOW()
             WHERE id = %(i)s::uuid
         RETURNING {_COLS}""",
        dict(fields, filters=json.dumps(fields['filters']), h=h, i=send_id)).fetchone())


def tested(row: dict, now: Optional[datetime] = None) -> bool:
    """The draft's current content was delivered to a test device in the
    last TEST_VALID."""
    now = now or _now()
    return bool(row['test_delivered_at'] and row['tested_hash'] == row['content_hash']
                and row['test_delivered_at'] > now - TEST_VALID)


# ---------------------------------------------------------------------------
# The test send
# ---------------------------------------------------------------------------

def _push_one(person_id: int, payload: dict, kind: str) -> int:
    """Send to every device the person has; how many took it. The test
    send's way, which reads no member toggle (the admin's own devices)."""
    from service.notifications import _send_to_user_blocking
    return _send_to_user_blocking(person_id, payload, kind=kind)


def payload(row: dict) -> dict:
    return dict(title=row['title'], body=row['body'], url=tap_url(row['url'], row['id']),
                tag=f"composer-{row['id']}")


# Test sends by this admin in the last 24 hours that reached the send guard
# (those with no device or no VAPID key never did).
_Q_TESTS_TODAY = '''
    SELECT count(*)::int AS n FROM admin_audit_log a
     WHERE a.action = 'push_composer_test'
       AND a.actor_uuid = (SELECT uuid FROM person WHERE id = %(p)s)
       AND a.created_at > NOW() - interval '24 hours'
       AND COALESCE(a.metadata->>'reason', '') NOT IN ('no_push_subscription', 'vapid_missing', 'test_limit')
'''


def _test_limit() -> int:
    from smtp import guard
    return guard.limit('push_per_kind')


def test_send(send_id: str, admin_person_id: int, now: Optional[datetime] = None) -> dict:
    """Push the draft to the signed-in admin's own devices and record the
    result against the draft. Works while the switch is off."""
    from database import api_tx
    from service.notifications import PUSH_ENABLED
    now = now or _now()
    with api_tx('read committed') as tx:
        row = get(tx, send_id)
        if row is None:
            raise Refused('not_found', 404)
        if row['state'] not in OPEN_STATES:
            raise Refused('not_a_draft')
        has_device = tx.execute("SELECT 1 FROM push_subscription WHERE person_id = %(p)s LIMIT 1",
                                dict(p=admin_person_id)).fetchone() is not None
        tests_today = tx.execute(_Q_TESTS_TODAY, dict(p=admin_person_id)).fetchone()['n']
    if not PUSH_ENABLED:
        why: Optional[str] = 'vapid_missing'
    elif not has_device:
        why = 'no_push_subscription'
    elif tests_today >= _test_limit():
        # The send guard lets one person have this many pushes of one kind
        # a day; past it the push would be refused and read as "not
        # delivered". Said as what it is instead.
        why = 'test_limit'
    else:
        try:
            why = None if _push_one(admin_person_id, payload(row), TEST_KIND) else 'not_delivered'
        except Exception:
            print(traceback.format_exc())
            why = 'error'
    with api_tx() as tx:
        # Only if the content is still what was pushed: an edit in between
        # leaves the draft untested.
        tx.execute("""UPDATE push_composer_send
                         SET test_delivered_at = CASE WHEN %(ok)s THEN %(now)s ELSE test_delivered_at END,
                             tested_hash = CASE WHEN %(ok)s THEN content_hash ELSE tested_hash END,
                             state = CASE WHEN %(ok)s THEN 'tested' ELSE state END,
                             test_result = %(res)s, updated_at = NOW()
                       WHERE id = %(i)s::uuid AND content_hash = %(h)s AND state IN ('draft', 'tested')""",
                   dict(ok=why is None, now=now, res=why or 'delivered', i=send_id, h=row['content_hash']))
    return dict(delivered=why is None, reason=why, send_id=send_id)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def _bb_day(at: datetime) -> date:
    return at.astimezone(BARBADOS).date()


def parse_when(when: Any, mode: Any, now: datetime) -> dict:
    """{scheduled_for, local_at, hold_until, mode} for a send, or Refused.
    'now' goes on the next pass. An ISO time without an offset is a wall
    clock time: Barbados time, or each member's own (member_local). With an
    offset it is that instant (barbados mode only)."""
    if mode not in ('barbados', 'member_local'):
        raise Refused('invalid_mode', 400)
    if when == 'now':
        if mode != 'barbados':
            raise Refused('invalid_mode', 400)
        return dict(scheduled_for=now, local_at=None, hold_until=now + HOLD_WINDOW, mode=mode, now=True)
    if not isinstance(when, str):
        raise Refused('invalid_when', 400)
    try:
        at = datetime.fromisoformat(when)
    except ValueError:
        raise Refused('invalid_when', 400)
    if mode == 'barbados':
        at = at.replace(tzinfo=BARBADOS) if at.tzinfo is None else at
        return dict(scheduled_for=at, local_at=None, hold_until=at + HOLD_WINDOW, mode=mode, now=False)
    if at.tzinfo is not None:
        raise Refused('invalid_when', 400)
    # The first member is due when the slot comes in the earliest zone, the
    # last when it comes in the latest; the hold window runs from there.
    return dict(scheduled_for=at.replace(tzinfo=_EARLIEST), local_at=at,
                hold_until=at.replace(tzinfo=_LATEST) + HOLD_WINDOW, mode=mode, now=False)


def slot_problem(slot: dict, now: datetime) -> Optional[str]:
    """Why a slot may not be scheduled: 'past', 'rest_day' or 'unknown'
    (after KNOWN_THROUGH), from restdays.slot_problem; for send now,
    resting(now). A member_local slot is read in Barbados time, the zone
    the rest calendar is kept in, and again at both ends of its range;
    members reached inside a rest period are held whatever the slot."""
    if slot['now']:
        if restdays.is_beyond_known(now):
            return 'unknown'
        return 'rest_day' if restdays.is_rest_period(now) else None
    if slot['mode'] == 'barbados':
        return restdays.slot_problem(slot['scheduled_for'], now)
    bb = slot['local_at'].replace(tzinfo=BARBADOS)
    first = restdays.slot_problem(bb, now)
    if first:
        return first
    for at in (slot['scheduled_for'], slot['local_at'].replace(tzinfo=_LATEST)):
        if restdays.is_beyond_known(at):
            return 'unknown'
        if restdays.is_rest_period(at):
            return 'rest_day'
    return None


def _sends_that_day(tx, day: date, but: str) -> int:
    return tx.execute(
        """SELECT count(*)::int AS n FROM push_composer_send
            WHERE id <> %(i)s::uuid AND state IN ('scheduled', 'sending', 'sent')
              AND COALESCE(local_at::date, (scheduled_for AT TIME ZONE 'America/Barbados')::date) = %(d)s""",
        dict(i=but, d=day)).fetchone()['n']


def send(tx, send_id: str, when: Any, mode: Any, now: Optional[datetime] = None) -> tuple[dict, bool]:
    """Freeze a tested draft into a send. Returns (row, repeat): a second
    press, or a retry, with the same content returns the first send with
    repeat True; the same draft pressed with another time is refused
    (already_sent). Raises Refused for everything else. Run it in a read
    committed transaction, so the day count read after the advisory lock
    sees a send another transaction committed meanwhile."""
    now = now or _now()
    row = get(tx, send_id, lock=True)
    if row is None:
        raise Refused('not_found', 404)
    key = f"{row['id']}:{row['content_hash']}"
    if row['state'] not in OPEN_STATES:
        if row['idempotency_key'] == key:
            if row['requested_when'] == str(when) and row['mode'] == mode:
                return row, True
            # The same draft pressed again with another time: never answer
            # as though the new time was taken.
            raise Refused('already_sent', state=row['state'], mode=row['mode'],
                          scheduled_for=_iso(row['scheduled_for']), local_at=_iso(row['local_at']))
        raise Refused('not_a_draft')
    if not tested(row, now):
        raise Refused('test_required')
    # The url's page may have closed since the draft was written.
    check_url(row['url'])
    slot = parse_when(when, mode, now)
    problem = slot_problem(slot, now)
    if problem:
        raise Refused(problem)
    day = _bb_day(slot['scheduled_for'] if slot['mode'] == 'barbados'
                  else slot['local_at'].replace(tzinfo=BARBADOS))
    # One send at a time past this point, so 2 at once cannot both see 1.
    _xact_lock(tx, _LOCK_SENDS)
    if _sends_that_day(tx, day, row['id']) >= DAY_SENDS:
        raise Refused('day_limit', most=DAY_SENDS)
    n = len(audience(tx, row['filters'], row['testers_only']))
    if n == 0:
        raise Refused('empty_audience')
    if n > max_audience():
        raise Refused('over_cap', most=max_audience(), count=n)
    out = tx.execute(
        f"""UPDATE push_composer_send
               SET state = 'scheduled', idempotency_key = %(k)s, scheduled_for = %(at)s, mode = %(m)s,
                   local_at = %(local)s, hold_until = %(hold)s, audience = %(n)s,
                   requested_when = %(w)s, updated_at = NOW()
             WHERE id = %(i)s::uuid AND state IN ('draft', 'tested')
         RETURNING {_COLS}""",
        dict(k=key, at=slot['scheduled_for'], m=slot['mode'], local=slot['local_at'],
             hold=slot['hold_until'], n=n, w=str(when), i=row['id'])).fetchone()
    return dict(out), False


def cancel(tx, send_id: str, now: Optional[datetime] = None) -> dict:
    """Cancel a scheduled or sending send: members already sent stay sent,
    everyone still waiting is released. Raises Refused otherwise."""
    row = get(tx, send_id, lock=True)
    if row is None:
        raise Refused('not_found', 404)
    if row['state'] not in LIVE_STATES:
        raise Refused('not_cancellable')
    tx.execute("""UPDATE push_composer_recipient SET state = 'released', reason = 'cancelled', updated_at = NOW()
                   WHERE send_id = %(i)s::uuid AND state IN ('pending', 'held')""", dict(i=send_id))
    tx.execute("""UPDATE push_composer_send SET state = 'cancelled', cancelled_at = NOW(), updated_at = NOW()
                   WHERE id = %(i)s::uuid""", dict(i=send_id))
    _recount(tx, send_id)
    return get(tx, send_id)


# ---------------------------------------------------------------------------
# The dry run
# ---------------------------------------------------------------------------

_Q_MEMBER_RECENT = f"""
    SELECT person_id,
           count(*) FILTER (WHERE sent_at > %(short)s)::int AS short_n,
           count(*) FILTER (WHERE sent_at > %(long)s)::int AS long_n
      FROM push_send_log
     WHERE campaign = '{CAMPAIGN}' AND person_id = ANY(%(ids)s) AND sent_at > %(long)s
       AND campaign_id <> %(own)s AND campaign_id <> %(own_pending)s
     GROUP BY person_id
"""


def _recent(tx, ids: list[int], now: datetime, own: str = '') -> dict[int, tuple[int, int]]:
    """Composer pushes each member had in the two cap windows, delivered or
    in flight, other than this send's own."""
    if not ids:
        return {}
    rows = tx.execute(_Q_MEMBER_RECENT, dict(ids=ids, short=now - MEMBER_SHORT[0], long=now - MEMBER_LONG[0],
                                             own=own, own_pending=f'{own}:pending')).fetchall()
    return {r['person_id']: (r['short_n'], r['long_n']) for r in rows}


def _over_member_cap(recent: tuple[int, int]) -> bool:
    return recent[0] >= MEMBER_SHORT[1] or recent[1] >= MEMBER_LONG[1]


def _day_pushes(tx, now: datetime) -> int:
    start = datetime.combine(_bb_day(now), time(0, 0), BARBADOS)
    return tx.execute(f"""SELECT count(*)::int AS n FROM push_send_log
                           WHERE campaign = '{CAMPAIGN}' AND sent_at >= %(s)s""", dict(s=start)).fetchone()['n']


def _due(row: dict, tz: Optional[str], now: datetime) -> bool:
    if row['mode'] != 'member_local':
        return now >= row['scheduled_for']
    return now.astimezone(zone(tz)).replace(tzinfo=None) >= row['local_at']


def _dry_run_probe() -> None:
    """A test hook: called once inside a dry run's no_send()."""


def dry_run(send_id: Optional[str] = None, fields: Optional[dict] = None,
            now: Optional[datetime] = None) -> dict:
    """What a send of this draft (or these fields) would do now: who would
    get it, who would be held and why, who is over a member cap and
    whether the send is over its own. Writes nothing; runs inside the send
    guard's no_send(), so a push made by mistake raises."""
    from database import api_tx
    from smtp import guard
    now = now or _now()
    with guard.no_send():
        _dry_run_probe()
        with api_tx('read committed') as tx:
            if send_id is not None:
                row = get(tx, send_id)
                if row is None:
                    raise Refused('not_found', 404)
                fields = dict(title=row['title'], body=row['body'], url=row['url'],
                              filters=row['filters'], testers_only=row['testers_only'])
            assert fields is not None
            rows = audience(tx, fields['filters'], fields['testers_only'])
            recent = _recent(tx, [r['person_id'] for r in rows], now, own=send_id or '')
            day_used = _day_pushes(tx, now)
    rest = resting(now)
    would = quiet_n = capped = 0
    for r in rows:
        if _over_member_cap(recent.get(r['person_id'], (0, 0))):
            capped += 1
        elif rest:
            continue
        elif _quiet_at(r['tz'], now):
            quiet_n += 1
        else:
            would += 1
    day_left = max(0, DAY_PUSHES - day_used)
    cap = max_audience()
    return dict(dry_run=True, audience=len(rows), would_send_now=min(would, day_left),
                held=dict(quiet=quiet_n, resting=(len(rows) - capped) if rest else 0),
                capped=capped, over_day_cap=max(0, would - day_left),
                over_send_cap=len(rows) > cap, max_audience=cap, switch_on=switch_on())


# ---------------------------------------------------------------------------
# The pass (the cron tick)
# ---------------------------------------------------------------------------

def _push_member(person_id: int, push: dict, kind: str) -> int:
    from service.notifications import send_to_user_counted
    return send_to_user_counted(person_id, push['title'], push['body'], push['url'], push['tag'],
                                event_kind='announcement', kind=kind)


def _claim(tx, person_id: int, send_id: str) -> bool:
    return tx.execute(
        f"""INSERT INTO push_send_log (person_id, campaign, campaign_id)
            SELECT %(p)s, '{CAMPAIGN}', %(pc)s
             WHERE NOT EXISTS (SELECT 1 FROM push_send_log
                                WHERE person_id = %(p)s AND campaign = '{CAMPAIGN}' AND campaign_id = %(c)s)
            ON CONFLICT (person_id, campaign, campaign_id) DO UPDATE SET sent_at = NOW()
             WHERE push_send_log.sent_at < NOW() - make_interval(mins => {PENDING_RETRY_MINUTES})
            RETURNING person_id""",
        dict(p=person_id, c=send_id, pc=f'{send_id}:pending')).fetchone() is not None


def _set_recipient(tx, send_id: str, person_id: int, state: str, reason: Optional[str] = None,
                   attempt: bool = False) -> None:
    tx.execute("""UPDATE push_composer_recipient
                     SET state = %(s)s, reason = %(r)s, updated_at = NOW(),
                         attempts = attempts + CASE WHEN %(a)s THEN 1 ELSE 0 END
                   WHERE send_id = %(i)s::uuid AND person_id = %(p)s""",
               dict(s=state, r=reason, a=attempt, i=send_id, p=person_id))


_Q_RECOUNT = """
    UPDATE push_composer_send s
       SET sent = c.sent, held = c.held, capped = c.capped, failed = c.failed, expired = c.expired,
           released = c.released, skipped = c.skipped, audience = COALESCE(c.total, s.audience),
           updated_at = NOW()
      FROM (SELECT count(*) FILTER (WHERE state = 'sent')::int AS sent,
                   count(*) FILTER (WHERE state IN ('pending', 'held', 'claimed'))::int AS held,
                   count(*) FILTER (WHERE state = 'capped')::int AS capped,
                   count(*) FILTER (WHERE state = 'failed')::int AS failed,
                   count(*) FILTER (WHERE state = 'expired')::int AS expired,
                   count(*) FILTER (WHERE state = 'released')::int AS released,
                   count(*) FILTER (WHERE state = 'skipped')::int AS skipped,
                   NULLIF(count(*), 0)::int AS total
              FROM push_composer_recipient WHERE send_id = %(i)s::uuid) c
     WHERE s.id = %(i)s::uuid
"""


def _recount(tx, send_id: str) -> None:
    tx.execute(_Q_RECOUNT, dict(i=send_id))


def _halt(send_id: str, reason: Optional[str]) -> None:
    from database import api_tx
    with api_tx() as tx:
        tx.execute("UPDATE push_composer_send SET halt_reason = %(r)s, updated_at = NOW() WHERE id = %(i)s::uuid",
                   dict(r=reason, i=send_id))


def _claim_pass(send_id: str, now: datetime) -> tuple[list[dict], Optional[str], Optional[str]]:
    """One transaction: take the pass lease, freeze the audience on the
    first pass, settle every waiting member's state for now, and claim
    those due. Returns the claimed pushes, the halt reason, if any, and the
    lease token (None when this pass may not send)."""
    from database import api_tx
    with api_tx('read committed') as tx:
        row = tx.execute(f"""SELECT {_COLS}, pass_token IS NOT NULL
                                    AND pass_heartbeat_at > NOW() - make_interval(mins => {LEASE_STALE_MINUTES})
                                    AS lease_live
                               FROM push_composer_send WHERE id = %(i)s::uuid
                                FOR UPDATE SKIP LOCKED""", dict(i=send_id)).fetchone()
        if row is None:
            return [], 'pass_running', None      # another pass is claiming
        row = dict(row)
        if row['state'] not in LIVE_STATES or row['scheduled_for'] > now:
            return [], None, None
        if row['lease_live']:
            return [], 'pass_running', None      # another pass is still pushing
        token = uuid4().hex
        tx.execute("""UPDATE push_composer_send SET pass_token = %(t)s, pass_heartbeat_at = NOW()
                       WHERE id = %(i)s::uuid""", dict(t=token, i=send_id))
        # One pass's cap read and claims at a time, across every send.
        _xact_lock(tx, _LOCK_CLAIMS)
        if row['state'] == 'scheduled':
            # The freeze: one pass over this audience, never a second.
            ids = [r['person_id'] for r in audience(tx, row['filters'], row['testers_only'])]
            if len(ids) > max_audience():
                # More joined the audience between the schedule and the
                # send: the cap holds at the send too, and nobody is pushed.
                tx.execute("""UPDATE push_composer_send
                                 SET state = 'failed', halt_reason = 'over_cap', audience = %(n)s,
                                     finished_at = %(now)s, updated_at = NOW()
                               WHERE id = %(i)s::uuid""", dict(i=send_id, n=len(ids), now=now))
                return [], 'over_cap', None
            tx.execute("""INSERT INTO push_composer_recipient (send_id, person_id)
                          SELECT %(i)s::uuid, unnest(%(ids)s::int[]) ON CONFLICT DO NOTHING""",
                       dict(i=send_id, ids=ids))
            tx.execute("""UPDATE push_composer_send SET state = 'sending', started_at = %(now)s,
                                 audience = %(n)s, updated_at = NOW() WHERE id = %(i)s::uuid""",
                       dict(i=send_id, now=now, n=len(ids)))
            row['state'] = 'sending'
        waiting = [dict(r) for r in tx.execute(
            f"""SELECT r.person_id, r.attempts, {_tz('p')} AS tz
                  FROM push_composer_recipient r JOIN person p ON p.id = r.person_id
                 WHERE r.send_id = %(i)s::uuid
                   AND (r.state IN ('pending', 'held')
                        -- A claim a restart left between the claim and the
                        -- settle: its push_send_log row is taken over too.
                        OR (r.state = 'claimed'
                            AND r.updated_at < NOW() - make_interval(mins => {PENDING_RETRY_MINUTES})))
                 ORDER BY r.person_id""", dict(i=send_id)).fetchall()]
        still = _still_in(tx, [w['person_id'] for w in waiting], row['testers_only'])
        recent = _recent(tx, [w['person_id'] for w in waiting], now, own=send_id)
        day_left = DAY_PUSHES - _day_pushes(tx, now)
        rest = resting(now)
        push = payload(row)
        claimed: list[dict] = []
        halt = None
        for w in waiting:
            pid = w['person_id']
            if pid not in still:
                _set_recipient(tx, send_id, pid, 'skipped', 'left_audience')
            elif now >= row['hold_until']:
                _set_recipient(tx, send_id, pid, 'expired', 'hold_window')
            elif _over_member_cap(recent.get(pid, (0, 0))):
                _set_recipient(tx, send_id, pid, 'capped', 'member_cap')
            elif rest:
                _set_recipient(tx, send_id, pid, 'held', 'resting')
            elif not _due(row, w['tz'], now):
                _set_recipient(tx, send_id, pid, 'held', 'not_yet')
            elif _quiet_at(w['tz'], now):
                _set_recipient(tx, send_id, pid, 'held', 'quiet')
            elif len(claimed) >= day_left:
                _set_recipient(tx, send_id, pid, 'held', 'day_cap')
                halt = 'day_cap'
            elif _claim(tx, pid, send_id):
                _set_recipient(tx, send_id, pid, 'claimed', None, attempt=True)
                claimed.append(dict(person_id=pid, push=push, attempts=w['attempts'] + 1))
            else:
                # Delivered already, or another pass's claim is young.
                _set_recipient(tx, send_id, pid, 'held', 'in_flight')
        tx.execute("UPDATE push_composer_send SET halt_reason = %(h)s WHERE id = %(i)s::uuid",
                   dict(h=halt, i=send_id))
        _recount(tx, send_id)
    return claimed, halt, token


def _renew(send_id: str, token: str) -> bool:
    """Renew the pass lease; False when another pass has taken it over."""
    from database import api_tx
    with api_tx() as tx:
        return tx.execute("""UPDATE push_composer_send SET pass_heartbeat_at = NOW()
                              WHERE id = %(i)s::uuid AND pass_token = %(t)s RETURNING 1""",
                          dict(i=send_id, t=token)).fetchone() is not None


def _settle(send_id: str, person_id: int, went: bool, attempts: int) -> None:
    from database import api_tx
    with api_tx() as tx:
        cancelled = tx.execute("SELECT state = 'cancelled' AS c FROM push_composer_send WHERE id = %(i)s::uuid",
                               dict(i=send_id)).fetchone()['c']
        if went:
            tx.execute(f"""UPDATE push_send_log SET campaign_id = %(c)s, sent_at = NOW()
                            WHERE person_id = %(p)s AND campaign = '{CAMPAIGN}' AND campaign_id = %(pc)s""",
                       dict(p=person_id, c=send_id, pc=f'{send_id}:pending'))
            _set_recipient(tx, send_id, person_id, 'sent')
        else:
            tx.execute(f"""DELETE FROM push_send_log
                            WHERE person_id = %(p)s AND campaign = '{CAMPAIGN}' AND campaign_id = %(pc)s""",
                       dict(p=person_id, pc=f'{send_id}:pending'))
            if cancelled:
                # Cancelled while this push was in flight: nothing more goes.
                _set_recipient(tx, send_id, person_id, 'released', 'cancelled')
            elif attempts >= MAX_ATTEMPTS:
                _set_recipient(tx, send_id, person_id, 'failed', 'no_device_took_it')
            else:
                _set_recipient(tx, send_id, person_id, 'pending', 'retry')


def _finish(send_id: str, token: Optional[str] = None) -> dict:
    from database import api_tx
    with api_tx() as tx:
        if token:
            tx.execute("""UPDATE push_composer_send SET pass_token = NULL
                           WHERE id = %(i)s::uuid AND pass_token = %(t)s""", dict(i=send_id, t=token))
        _recount(tx, send_id)
        tx.execute("""UPDATE push_composer_send
                         SET state = 'sent', finished_at = NOW(), updated_at = NOW()
                       WHERE id = %(i)s::uuid AND state = 'sending'
                         AND NOT EXISTS (SELECT 1 FROM push_composer_recipient
                                          WHERE send_id = %(i)s::uuid
                                            AND state IN ('pending', 'held', 'claimed'))""",
                   dict(i=send_id))
        return get(tx, send_id) or {}


def run_send(send_id: str, now: Optional[datetime] = None) -> dict:
    """One pass of one send. Sends nothing while the switch is off or push
    has no VAPID keys; says why on the row instead."""
    from service.notifications import PUSH_ENABLED
    now = now or _now()
    if not switch_on():
        return dict(send_id=send_id, handed=0, went=0, halted='switch_off')
    if not PUSH_ENABLED:
        _halt(send_id, 'vapid_missing')
        return dict(send_id=send_id, handed=0, went=0, halted='vapid_missing')
    claimed, halt, token = _claim_pass(send_id, now)
    if token is None:
        return dict(send_id=send_id, handed=0, went=0, halted=halt, state=None)
    went, lost = _deliver(send_id, token, claimed)
    row = _finish(send_id, token)
    out = dict(send_id=send_id, handed=len(claimed), went=went, halted='lease_lost' if lost else halt,
               state=row.get('state'))
    if claimed:
        print('PUSH_COMPOSER ' + json.dumps(out), flush=True)
    return out


def _deliver(send_id: str, token: str, claimed: list[dict]) -> tuple[int, bool]:
    """Push each claim, renewing the lease before each one and settling it
    in its own committed transaction straight after. Stops, leaving the
    rest claimed, if another pass has taken the lease. Returns (how many
    went, whether the lease was lost)."""
    went = 0
    kind = f'{CAMPAIGN}:{send_id}'
    for c in claimed:
        if not _renew(send_id, token):
            return went, True
        try:
            n = _push_member(c['person_id'], c['push'], kind)
        except Exception:
            print(traceback.format_exc())
            n = 0
        try:
            _settle(send_id, c['person_id'], bool(n), c['attempts'])
            went += 1 if n else 0
        except Exception:
            print(traceback.format_exc())
    return went, False


def due_ids(now: Optional[datetime] = None) -> list[str]:
    from database import api_tx
    now = now or _now()
    with api_tx('read committed') as tx:
        return [r['id'] for r in tx.execute(
            """SELECT id::text AS id FROM push_composer_send
                WHERE state IN ('scheduled', 'sending') AND scheduled_for <= %(now)s
                ORDER BY scheduled_for, id""", dict(now=now)).fetchall()]


def tick(now: Optional[datetime] = None) -> dict:
    """The cron's tick: one pass of every due send. Nothing while the
    switch is off."""
    now = now or _now()
    if not switch_on():
        return {}
    out = {}
    for sid in due_ids(now):
        try:
            out[sid] = run_send(sid, now)
        except Exception:
            print(traceback.format_exc())
            out[sid] = 'error'
    return out


def run_soon(send_id: str) -> None:
    """Send now: a pass on a thread once the route's transaction has
    committed, rather than waiting up to 10 minutes for the tick. The tick
    and this pass never both send to a member: the pass lease keeps the
    tick out while this pass is alive, and each member is claimed in
    push_send_log first."""
    from smtp import guard
    guard.spawn(_run_quietly, send_id)


def _run_quietly(send_id: str) -> None:
    try:
        run_send(send_id)
    except Exception:
        print(traceback.format_exc())


# ---------------------------------------------------------------------------
# What the admin reads
# ---------------------------------------------------------------------------

def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def public(tx, row: dict, now: Optional[datetime] = None) -> dict:
    """A send as the admin card reads it: never a member's name or
    address."""
    now = now or _now()
    tapped = tx.execute("""SELECT count(DISTINCT person_id)::int AS n FROM push_tap
                            WHERE src = 'apush' AND send_id = %(i)s::uuid""", dict(i=row['id'])).fetchone()['n']
    held_by = {r['reason'] or 'waiting': r['n'] for r in tx.execute(
        """SELECT reason, count(*)::int AS n FROM push_composer_recipient
            WHERE send_id = %(i)s::uuid AND state IN ('pending', 'held', 'claimed')
            GROUP BY reason""", dict(i=row['id'])).fetchall()}
    keys = ('id', 'title', 'body', 'url', 'filters', 'testers_only', 'state', 'mode', 'scheduled_for',
            'local_at', 'hold_until', 'test_delivered_at', 'test_result', 'halt_reason', 'created_at',
            'updated_at', 'started_at', 'finished_at', 'cancelled_at')
    out = {k: _iso(row[k]) for k in keys}
    out.update(tested=tested(row, now), can_send=row['state'] in OPEN_STATES and tested(row, now),
               results=dict(audience=row['audience'], sent=row['sent'], held=row['held'],
                            capped=row['capped'], failed=row['failed'], expired=row['expired'],
                            released=row['released'], skipped=row['skipped'], tapped=tapped),
               held_by=held_by, tap_url=tap_url(row['url'], row['id']))
    return out


def list_sends(tx, limit: int = 50) -> list[dict]:
    rows = [dict(r) for r in tx.execute(f"SELECT {_COLS} FROM push_composer_send "
                                        "ORDER BY created_at DESC LIMIT %(l)s", dict(l=limit)).fetchall()]
    return [public(tx, r) for r in rows]


def config() -> dict:
    """What the card needs before anything is typed: the switch, the tap
    targets, the limits and the filters' allowed values."""
    return dict(enabled=switch_on(), urls=url_options(),
                limits=dict(title=TITLE_MAX, body=BODY_MAX, max_audience=max_audience(),
                            member_72h=MEMBER_SHORT[1], member_7d=MEMBER_LONG[1],
                            sends_per_day=DAY_SENDS, pushes_per_day=DAY_PUSHES,
                            hold_hours=int(HOLD_WINDOW.total_seconds() // 3600),
                            test_valid_hours=int(TEST_VALID.total_seconds() // 3600)),
                filters=dict(keys=list(FILTER_KEYS), gender=list(GENDERS), tiers=list(TIERS),
                             online_days=list(ONLINE_DAYS), joined_days=[1, 365]),
                known_through=restdays.KNOWN_THROUGH.isoformat())


def audit_meta(row: dict, **extra) -> dict:
    """An audit row's metadata: the send id, a hash of the filters, the
    audience count, the title and the url. Never an address."""
    return dict(send_id=row['id'], filters_hash=filters_hash(row['filters']), audience=row.get('audience'),
                title=row['title'], url=row['url'], testers_only=row['testers_only'], **extra)
