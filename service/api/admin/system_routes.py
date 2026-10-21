"""System tab — health snapshot."""
from __future__ import annotations

import duotypes as t

from service.api.decorators import aget
from service.admin import require_admin
from service.admin.queries import (
    Q_SYSTEM_HEALTH, Q_OTP_24H, Q_OUTBOX_HEALTH, Q_FEEDBACK_RECENT,
    Q_VERIFICATION_JOBS, Q_OTP_DAILY, Q_OTP_REFUSALS_30D)
from service.verificationlease import (
    VERIFICATION_LEASE_SECONDS,
    VERIFICATION_MAX_REAPS,
)
from database import api_tx


@aget('/admin/system/health')
def get_system_health(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        health = tx.execute(Q_SYSTEM_HEALTH).fetchone() or {}
        otp = tx.execute(Q_OTP_24H).fetchone() or {}
        # Codes requested and never entered, per day, new and existing
        # addresses apart, and why requests were refused (TEC-1848).
        otp_daily = tx.execute(Q_OTP_DAILY).fetchall()
        otp_refusals = tx.execute(Q_OTP_REFUSALS_30D).fetchall()
        # Campaign email delivery. In the same transaction as the rest: the
        # api connection lock is not reentrant, so a second api_tx here
        # would deadlock the request.
        outbox = tx.execute(Q_OUTBOX_HEALTH).fetchone() or {}
        # Member feedback, which until now nothing anywhere read.
        feedback = [dict(r) for r in tx.execute(Q_FEEDBACK_RECENT).fetchall()]
        # The counts are read against the same lease and ceiling the cron
        # claims with, so what the operator calls stuck is exactly what the
        # reaper gave up on.
        verification = tx.execute(
            Q_VERIFICATION_JOBS,
            dict(
                lease_seconds=VERIFICATION_LEASE_SECONDS,
                max_reaps=VERIFICATION_MAX_REAPS,
            ),
        ).fetchone() or {}
    return {
        'health': dict(health),
        'otp': dict(otp),
        # Oldest day first, today last; each day an ISO date (YYYY-MM-DD).
        'otp_daily': [dict(r, day=r['day'].isoformat()) for r in otp_daily],
        'otp_refusals_30d': [dict(r) for r in otp_refusals],
        # isoformat() rather than letting Flask's JSON provider have the raw
        # datetime: its default is an RFC 2822 HTTP-date ("Thu, 24 Sep 2026
        # 10:56:56 GMT"), every other timestamp on the admin surface is ISO
        # 8601, and the TypeScript that reads this one is typed and tested
        # against ISO.
        'outbox': dict(outbox, oldest_queued_at=(
            outbox['oldest_queued_at'].isoformat()
            if outbox.get('oldest_queued_at') else None)),
        'verification': dict(verification),
        'feedback': [dict(r, created_at=r['created_at'].isoformat()) for r in feedback],
    }


@aget('/admin/system/errors')
def get_system_errors(s: t.SessionInfo):
    """API errors (TEC-1897; frames E.1 to E.3). `available` is False when
    the tally cannot be read, which the card shows as "Error counter
    unavailable" rather than as no errors."""
    require_admin(s)
    import psycopg
    from service.api import error_tally
    try:
        with api_tx('read committed') as tx:
            return dict(available=True, **error_tally.summary(tx))
    except psycopg.Error:
        return dict(available=False, last_24h=None, last_7d=None, routes=[])
