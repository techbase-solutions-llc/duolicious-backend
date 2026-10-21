"""Send the owner one proof of each gathering email (TEC-1845), before any
of their switches is turned on.

    python -m scripts.send_event_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_event_proofs --send     # send the proofs

Run inside the api container (mailer settings). The same rules as
scripts/send_proofs.py, whose address and helpers this reuses: to
PROOF_TO only, straight through the mailer, never the outbox; sample data
only (Grace Fellowship, Marriage preparation evening, Hannah Okafor); no
switch read or changed. Every link that would carry a token (confirm,
cancel, the calendar file, the manage link, unsubscribe) points at
PROOF_LINK_DISABLED. It refuses to send while any of the 6 title images
is missing from emails/assets (it prints their stems and exits 1).
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

from scripts.send_proofs import PROOF_LINK_DISABLED, PROOF_TO, _inert, _smtp

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'plan', 'missing_titles', 'main']


def _inert_event_links(name: str, html: str) -> str:
    """Every link that would carry a guest's or an organiser's token, and
    every unsubscribe link, replaced by PROOF_LINK_DISABLED."""
    from service.config import API_BASE_URL, WEB_BASE_URL
    for base in {WEB_BASE_URL.rstrip('/'), API_BASE_URL.rstrip('/')}:
        b = re.escape(base)
        html = re.sub(b + r'/rsvp/[^"\'\s<>]+', PROOF_LINK_DISABLED, html)
        html = re.sub(b + r'/host/gatherings\?t=[^"\'\s<>]+', PROOF_LINK_DISABLED, html)
    return _inert(name, html)


def plan() -> list[dict]:
    """Every proof email, built from sample data, in the export's order.
    Writes nothing and reads no switch."""
    from service.events import mail
    builders = [
        ('event_confirm', 'Confirm your place, in person (3.1)', mail.preview_confirm),
        ('event_confirm_online', 'Confirm your place, online', mail.preview_confirm_online),
        ('event_reminder', 'Reminder, in person (3.2)', mail.preview_reminder),
        ('event_reminder_online', 'Reminder, online (3.3)', mail.preview_reminder_online),
        ('event_change', 'A change (3.4)', mail.preview_change),
        ('event_cancelled', 'Cancelled (3.5)', mail.preview_cancelled),
        ('event_digest', 'Daily digest to the organiser (3.6)', mail.preview_digest),
        ('event_manage', 'Your manage link (3.8)', mail.preview_manage),
        ('event_approved', 'Request to host approved (plan item 15)', mail.preview_approved),
        ('event_live', 'Gathering live (plan item 15)', mail.preview_live),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert_event_links(name, html), from_addr=mail.FROM_ADDR))
    return out


def missing_titles() -> list[str]:
    """The stems of the title images (light or dark) not in emails/assets."""
    import emails.base as base
    from service.events.mail import TITLES
    return [stem for stem, _alt, _width in TITLES.values()
            if not ((base.ASSETS_DIR / f'{stem}.png').is_file()
                    and (base.ASSETS_DIR / f'{stem}-wht.png').is_file())]


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails = plan()
    missing = missing_titles()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}")
    for e in emails:
        print(f"  email  {e['name']:22s} {e['subject']}  ({e['label']})")
    if missing:
        print('Title images missing from emails/assets (light and -wht): ' + ', '.join(missing))
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    if missing:
        print('Not sending: a proof without its title image is not the email the owner would approve.')
        sys.exit(1)
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO,
                        from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")


if __name__ == '__main__':
    main(sys.argv[1:])
