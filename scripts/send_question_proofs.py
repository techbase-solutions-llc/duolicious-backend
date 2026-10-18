"""Send the owner one proof of each quick-question email and push
(TEC-1845), before any of their switches is turned on.

    python -m scripts.send_question_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_question_proofs --send     # send the proofs

Run inside the api container (mailer settings and VAPID keys). The same
rules as scripts/send_proofs.py, whose address, account and helpers this
reuses: emails to PROOF_TO only, straight through the mailer, never the
outbox; pushes to account PUSH_PERSON_ID's subscriptions only, sent
directly; sample data only; no switch read or changed; every unsubscribe
link inert. Push links carry no ?src=, so a proof tap counts as nothing.
The launch email's answer buttons are inert too: a tap on /q/{key}/{choice}
would save the owner's own answer to a real question.

The tag check the spec asks for ("Whether iOS replaces by tag is
unverified; the owner's proof should test it"): the weekly and launch
proofs share the tag question:proof. On a device that replaces by tag,
only the launch proof is left once both have arrived.
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

from scripts.send_proofs import (PROOF_LINK_DISABLED, PROOF_TO, PUSH_PERSON_ID, _inert,
                                 _push_one, _smtp, _subscriptions)

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'PUSH_PERSON_ID', 'plan', 'main']


def _inert_answers(html: str) -> str:
    """Each answer link (/q/<key>/<choice>) replaced by PROOF_LINK_DISABLED."""
    from service.config import WEB_BASE_URL
    return re.sub(re.escape(WEB_BASE_URL.rstrip('/')) + r'/q/[^"\'\s<>]+', PROOF_LINK_DISABLED, html)


def _emails() -> list[dict]:
    from emails import questions_launch, send_community_weekly
    builders = [
        ('e2_question_line', 'Weekly email with the question line',
         send_community_weekly.preview_question_line, send_community_weekly.FROM_ADDR),
        ('questions_launch', 'The launch email',
         questions_launch.preview, questions_launch.FROM_ADDR),
    ]
    out = []
    for name, label, build, from_addr in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f"[PROOF] {subject}",
                        html=_inert_answers(_inert(name, html)), from_addr=from_addr))
    return out


def _pushes() -> list[dict]:
    from service.questions.copy import PUSH_PROOFS
    return [dict(p) for p in PUSH_PROOFS]


def plan() -> tuple[list[dict], list[dict]]:
    """Every proof email (built) and every proof push. Writes nothing."""
    return _emails(), _pushes()


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails, pushes = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}, "
          f"{len(pushes)} proof pushes to account {PUSH_PERSON_ID}")
    for e in emails:
        print(f"  email  {e['name']:17s} {e['subject']}  ({e['label']})")
    for p in pushes:
        print(f"  push   {p['kind']:17s} {p['title']}: {p['body']} -> {p['url']} [{p['tag']}]")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO, from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")
    subs = _subscriptions(PUSH_PERSON_ID)
    if not subs:
        print(f"account {PUSH_PERSON_ID} has no push subscription; no push sent")
    for p in pushes:
        payload = dict(title=f"[Proof] {p['title']}", body=p['body'], url=p['url'], tag=p['tag'])
        for sub in subs:
            status = _push_one(sub, payload)
            print(f"pushed {p['kind']} ({'ok' if status is None else status})")


if __name__ == '__main__':
    main(sys.argv[1:])
