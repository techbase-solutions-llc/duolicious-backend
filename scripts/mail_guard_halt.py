"""Halt mail at the send guard by hand (send safeguards plan, 2 Nov 2026).

    PYTHONPATH=/app python3 scripts/mail_guard_halt.py --all --reason "<why>" [--push] [--by <name>]
    PYTHONPATH=/app python3 scripts/mail_guard_halt.py --kind <kind> --reason "<why>" [--push]

The fastest stop that keeps sign-in codes going. The halt is sticky: it
stays until scripts/mail_guard_clear.py clears it. It alerts the owner on the
next sendguard tick. Exit 0 when the halt is new, 1 when it was already set.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument('--kind')
    target.add_argument('--all', action='store_true')
    ap.add_argument('--reason', required=True)
    ap.add_argument('--by', default='scripts/mail_guard_halt.py')
    ap.add_argument('--push', action='store_true', help='halt push rather than email')
    a = ap.parse_args(argv)
    from service import sendguard
    channel = 'push' if a.push else 'email'
    new = sendguard.set_halt(channel, None if a.all else a.kind, reason=a.reason, by=a.by)
    what = f'every non-essential {channel}' if a.all else f'{channel} of kind {a.kind}'
    print(f'Halted {what}.' if new else f'{what.capitalize()} was already halted.')
    return 0 if new else 1


if __name__ == '__main__':
    sys.exit(main())
