"""Send the owner one proof of the stale-post alert (TEC-1897), before its
switch is turned on.

    python -m scripts.send_admin_alert_proofs            # DRY RUN
    python -m scripts.send_admin_alert_proofs --send     # send the proof

Run inside the api container. The same rules as scripts/send_proofs.py,
whose address and helpers this reuses: to PROOF_TO only, straight through
the mailer, never the outbox; sample data only; no switch read or changed.
There is no report alert to proof: the report email that already goes to
DUO_REPORT_EMAIL is the report alert (tests/email_samples.py STAFF_report).
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from scripts.send_proofs import PROOF_TO, _inert, _smtp

__all__ = ['PROOF_TO', 'plan', 'main']


def plan() -> list[dict]:
    from emails import admin_alerts
    builders = [
        ('stale_post_alert', 'Posts waiting for approval (G.8)', admin_alerts.preview_stale),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert(name, html), from_addr=admin_alerts.FROM_ADDR))
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof email(s) to {PROOF_TO}")
    for e in emails:
        print(f"  email  {e['name']:20s} {e['subject']}  ({e['label']})")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO, from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")


if __name__ == '__main__':
    main(sys.argv[1:])
