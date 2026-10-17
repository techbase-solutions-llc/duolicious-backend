"""Send the owner one proof of each Together email (TEC-1845), before any
of their switches is turned on.

    python -m scripts.send_together_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_together_proofs --send     # send the proofs

Run inside the api container (mailer settings). The same rules as
scripts/send_proofs.py, whose address and helpers this reuses: to
PROOF_TO only, straight through the mailer, never the outbox; sample data
only (Rivka); no switch read or changed; every unsubscribe link inert.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from scripts.send_proofs import PROOF_LINK_DISABLED, PROOF_TO, _inert, _smtp

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'plan', 'main']


def plan() -> list[dict]:
    """Every proof email, built. Writes nothing."""
    from service.tools import mail
    builders = [
        ('together_answered', 'Us: the other player has answered (4.10)', mail.preview_answered),
        ('together_ready', 'Checklist: your comparison is ready (6.12)', mail.preview_ready),
        ('together_invite_game', 'Us: the invite sent by email (4.3)', mail.preview_invite_game),
        ('together_invite_checklist', 'Checklist: the invite sent by email (6.2)',
         mail.preview_invite_checklist),
        ('together_summary', 'Checklist summary with the stored-answers line (decision 12)',
         mail.preview_summary),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert(name, html), from_addr=mail.FROM_ADDR))
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}")
    for e in emails:
        print(f"  email  {e['name']:26s} {e['subject']}  ({e['label']})")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO,
                        from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")


if __name__ == '__main__':
    main(sys.argv[1:])
