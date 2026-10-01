"""Queue the referral intro for every member due one, to go out at a chosen
slot (TEC-1613).

    PYTHONPATH=/app python3 scripts/schedule_referral_intro.py --at 2026-10-03T12:00:00Z [--cap-days 1]

Owner decision 1 Oct 2026: the 25 intros the cron queued and the drain held
under the 7 day cap (those members had email 1 or 2 the same day) go out two
days later rather than waiting for next week's tick. The rows are queued now
with next_attempt_at at the slot, under an id that names the slot, so the
cron's own weekly row never collides with them. `--cap-days` is the window
the drain re-checks AT THE SLOT: 1 means "nothing else in the last day".

Members already accepted are excluded by the send log, as always.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from database import api_tx
from service.cron.referralintro import queue_due


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--at', required=True, help='ISO 8601 instant, e.g. 2026-10-03T12:00:00Z')
    ap.add_argument('--cap-days', type=int, default=1)
    a = ap.parse_args()
    at = datetime.fromisoformat(a.at.replace('Z', '+00:00')).astimezone(timezone.utc)
    if at <= datetime.now(timezone.utc):
        raise SystemExit('--at is in the past')
    suffix = 'sched' + at.strftime('%Y%m%dT%H%M')
    with api_tx() as tx:
        n = queue_due(tx, datetime.now(timezone.utc), cap_days=a.cap_days, not_before=at, id_suffix=suffix)
    print(f'queued {n} for {at.isoformat()} under referral-<id>-{suffix}, cap {a.cap_days} day(s)')


if __name__ == '__main__':
    main()
