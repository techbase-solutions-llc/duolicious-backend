"""Users tab routes — list + single-user drilldown.

GET /admin/users        — paginated list with search + filter pills
GET /admin/users/:uuid  — single-user blob (profile + photos + tokens + referrals + audit)
"""
from __future__ import annotations

import duotypes as t
from flask import request

from service.api.decorators import aget
from service.admin import MAX_PAGE, int_arg, require_admin, require_uuid
from service.admin.queries import (
    Q_USERS_LIST,
    Q_USERS_COUNT,
    Q_USER_PROFILE,
    Q_USER_PHOTOS,
    Q_USER_TOKEN_LEDGER,
    Q_USER_TOKEN_BALANCE,
    Q_USER_REFERRAL_STATS,
    Q_USER_AUDIT_LOG,
    Q_USER_WAITLIST_ANSWERS,
)
from database import api_tx
from service.admin.jsonrow import iso
from service.growth.queries import _excluded


_PAGE_SIZE = 20

_FILTER_KEYS = (
    'has_person', 'waitlist_only', 'beta_only',
    'unsubscribed', 'has_premium', 'role_admin', 'role_mod',
    'has_likes_waiting',
)


@aget('/admin/users')
def get_admin_users(s: t.SessionInfo):
    require_admin(s)
    q = (request.args.get('q') or '').strip()
    page = int_arg('page', 1, 1, MAX_PAGE)
    filters_raw = request.args.get('filters', '')
    active_filters = set(filters_raw.split(',')) if filters_raw else set()
    params = {
        'q': q,
        'q_like': f'%{q}%' if q else '%',
        'limit': _PAGE_SIZE,
        'offset': (page - 1) * _PAGE_SIZE,
        **{k: (k in active_filters) for k in _FILTER_KEYS},
        'ex': _excluded(),
    }
    with api_tx('read committed') as tx:
        rows = [dict(r, last_online_at=iso(r['last_online_at']),
                     joined_at=iso(r['joined_at']),
                     deletion_requested_at=iso(r['deletion_requested_at']))
                for r in tx.execute(Q_USERS_LIST, params).fetchall()]
        total_row = tx.execute(Q_USERS_COUNT, params).fetchone()
    total = int(total_row['total']) if total_row else 0
    return {
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': _PAGE_SIZE,
    }


@aget('/admin/users/<uuid>')
def get_admin_user_detail(s: t.SessionInfo, uuid: str):
    require_admin(s)
    require_uuid(uuid)
    with api_tx('read committed') as tx:
        profile = tx.execute(Q_USER_PROFILE, dict(uuid=uuid)).fetchone()
        if profile is None:
            # Could be a waitlist-only or beta-only row keyed by email.
            # Try to fetch by email from waitlist if uuid is actually an email.
            from flask import abort
            abort(404)
        photos = [dict(r) for r in tx.execute(Q_USER_PHOTOS, dict(uuid=uuid)).fetchall()]
        tokens_ledger = [dict(r) for r in tx.execute(Q_USER_TOKEN_LEDGER, dict(uuid=uuid)).fetchall()]
        balance_row = tx.execute(Q_USER_TOKEN_BALANCE, dict(uuid=uuid)).fetchone()
        referrals = tx.execute(Q_USER_REFERRAL_STATS, dict(uuid=uuid)).fetchone() or {}
        audit = [dict(r) for r in tx.execute(Q_USER_AUDIT_LOG, dict(uuid=uuid)).fetchall()]
        wl_row = tx.execute(Q_USER_WAITLIST_ANSWERS, dict(uuid=uuid)).fetchone()
    return {
        'profile': dict(profile),
        'photos': photos,
        'tokens': {
            'balance': int(balance_row['balance']) if balance_row else 0,
            'ledger': tokens_ledger,
        },
        'referrals': dict(referrals) if referrals else {'pending': 0, 'graduated': 0, 'credited': 0},
        'audit': audit,
        'waitlist_answers': (wl_row or {}).get('answers'),
    }


_ACTIVITY_PAGE = 50
_ACTIVITY_PAGE_MAX = 100
# The years a `from`, `to` or `before` may name. Ahavah began in 2026; the
# bound keeps the day arithmetic and the chat archive's id (a bigint) from
# overflowing on a date like 9999-12-31, which answered 500.
_ACTIVITY_YEARS = (2000, 2100)


def _activity_cursor(raw: str | None):
    """`before` is the previous page's `next_before`: an ISO time, and after
    a comma how many lines at exactly that time were already shown. None
    when absent; 400 when it is not one."""
    from datetime import datetime, timezone
    from flask import abort
    if not raw:
        return None, 0
    at_text, _, skip_text = raw.partition(',')
    try:
        # A '+' left unencoded in a query string arrives as a space.
        at = datetime.fromisoformat(
            at_text.strip().replace(' ', '+').replace('Z', '+00:00'))
        skip = int(skip_text) if skip_text else 0
    except ValueError:
        abort(400)
    if not _ACTIVITY_YEARS[0] <= at.year <= _ACTIVITY_YEARS[1]:
        abort(400)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at, max(0, min(skip, 10_000))


def _activity_day(name: str):
    """`from` / `to` as a Barbados day (YYYY-MM-DD), the dashboard's day
    (service/admin/queries/days.py). Returns the instant that day starts."""
    from datetime import date, datetime, time
    from zoneinfo import ZoneInfo
    from flask import abort
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        abort(400)
    if not _ACTIVITY_YEARS[0] <= d.year <= _ACTIVITY_YEARS[1]:
        abort(400)
    return datetime.combine(d, time.min, tzinfo=ZoneInfo('America/Barbados'))


def _archive_id(at) -> int:
    """The chat archive's id for an instant: microseconds since the epoch,
    shifted left 8 bits (service/chat/messagestorage/mam)."""
    return int(at.timestamp() * 1_000_000) << 8


@aget('/admin/users/<uuid>/activity')
def get_admin_user_activity(s: t.SessionInfo, uuid: str):
    """A member's activity timeline and 7 and 30 day summary (TEC-2092).

    ?type=all|interactions|messages|reports|money|account|community,
    ?limit= (50, at most 100), ?before= (the previous page's next_before),
    ?from= / ?to= (Barbados days, inclusive). Newest first.

    Opening it (the first page, any filter) writes a view_member_activity
    audit row. Message text is never read (service/admin/queries/
    activity.py)."""
    from datetime import datetime, timedelta, timezone
    from flask import abort
    from service.admin import record_audit
    from service.admin.queries.activity import (
        Q_MEMBER_ACTIVITY_SUMMARY, Q_MEMBER_FOR_ACTIVITY, SUMMARY_FIELDS,
        TYPES, timeline_sql)

    require_admin(s)
    require_uuid(uuid)
    kind = (request.args.get('type') or 'all').strip().lower()
    if kind != 'all' and kind not in TYPES:
        abort(400)
    types = TYPES if kind == 'all' else (kind,)
    page = int_arg('limit', _ACTIVITY_PAGE, 1, _ACTIVITY_PAGE_MAX)
    cursor, skip = _activity_cursor(request.args.get('before'))

    now = datetime.now(timezone.utc)
    start = _activity_day('from')
    end = _activity_day('to')
    lo = start or datetime(1970, 1, 1, tzinfo=timezone.utc)
    # The end of the `to` day, or a little past now so a line written as
    # the page loads is not lost.
    hi_end = (end + timedelta(days=1) - timedelta(microseconds=1)) if end else now + timedelta(days=1)
    hi = min(cursor, hi_end) if cursor else hi_end
    if cursor is None or cursor > hi_end:
        skip = 0

    def naive(at):
        return at.astimezone(timezone.utc).replace(tzinfo=None)

    t7, t30 = now - timedelta(days=7), now - timedelta(days=30)
    params = dict(
        lo=lo, hi=hi, hi_end=hi_end, lo_n=naive(lo), hi_n=naive(hi),
        lo_id=_archive_id(lo), hi_id=_archive_id(hi_end) + 255,
        skip=skip, page=page + 1, lim=skip + page + 1,
    )

    with api_tx() as tx:
        member = tx.execute(Q_MEMBER_FOR_ACTIVITY, dict(uuid=uuid)).fetchone()
        if member is None:
            abort(404)
        params.update(pid=member['id'], puuid=member['uuid'])
        rows = tx.execute(timeline_sql(types), params).fetchall()
        summary_row = tx.execute(Q_MEMBER_ACTIVITY_SUMMARY, dict(
            pid=member['id'], t7=t7, t30=t30, t7_n=naive(t7), t30_n=naive(t30),
            id7=_archive_id(t7), id30=_archive_id(t30))).fetchone()
        if cursor is None:
            record_audit(
                tx, s, 'view_member_activity',
                target_email=member['email'], target_uuid=member['uuid'],
                metadata={'type': kind,
                          'from': request.args.get('from') or None,
                          'to': request.args.get('to') or None})

    more = len(rows) > page
    rows = rows[:page]
    items = []
    for r in rows:
        item: dict = {'kind': r['kind'], 'at': iso(r['at']), 'other': None}
        if r['other_uuid']:
            item['other'] = {'uuid': r['other_uuid'], 'name': r['other_name'] or None,
                             'staff': bool(r['other_staff'])}
        if r['n'] is not None:
            item['count'] = int(r['n'])
        detail = r['detail']
        if r['has_other'] and not r['other_uuid']:
            detail = 'deleted'
        if detail is not None:
            item['detail'] = detail
        items.append(item)

    next_before = None
    if more and rows:
        last_at = rows[-1]['at']
        same = sum(1 for r in rows if r['at'] == last_at)
        if cursor is not None and last_at == hi:
            same += skip
        stamp = last_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        next_before = f"{stamp},{same}"

    summary = {w: {f: int(summary_row[f'{f}_{w}'] or 0) for f in SUMMARY_FIELDS}
               for w in ('d7', 'd30')}
    return {'summary': summary, 'items': items, 'next_before': next_before}
