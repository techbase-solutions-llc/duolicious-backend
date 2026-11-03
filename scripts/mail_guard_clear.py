"""Clear a send guard halt (send safeguards plan, 2 Nov 2026).

    PYTHONPATH=/app python3 scripts/mail_guard_clear.py --kind <kind> --by <name> [--push]
    PYTHONPATH=/app python3 scripts/mail_guard_clear.py --all --by <name> [--push]

Clears Redis and Postgres together and records who cleared it. Clearing only
Redis by hand does not work: the sendguard cron puts back, within a minute,
any halt still open in Postgres. Exit 0 when a halt was cleared, 1 when
there was none.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument('--kind')
    target.add_argument('--all', action='store_true')
    ap.add_argument('--by', required=True)
    ap.add_argument('--push', action='store_true', help='a push halt rather than an email halt')
    a = ap.parse_args(argv)
    from service import sendguard
    channel = 'push' if a.push else 'email'
    cleared = sendguard.clear_halt(channel, None if a.all else a.kind, by=a.by)
    what = f'every non-essential {channel}' if a.all else f'{channel} of kind {a.kind}'
    print(f'Cleared the halt on {what}.' if cleared else f'There was no halt on {what}.')
    return 0 if cleared else 1


if __name__ == '__main__':
    sys.exit(main())
