"""Send the owner one proof of each matchmaker email and push (TEC-1845),
before any of their switches is turned on.

    python -m scripts.send_matchmaker_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_matchmaker_proofs --send     # send the 8 proof emails
    python -m scripts.send_matchmaker_proofs --push     # send the 3 proof pushes

Run inside the api container (mailer settings, VAPID keys). The rules of
scripts/send_proofs.py, whose address and helpers this reuses: emails to
PROOF_TO only, straight through the mailer, never the outbox; pushes to
account PUSH_PERSON_ID's subscriptions only, sent directly; sample data
only (Hannah, Miriam, Rivka; 2 members; 5 likes); no switch read or
changed. Every link that would carry a token or a code (confirm, stop, the
mentor's invitation, the referral link, an introduction, unsubscribe)
points at PROOF_LINK_DISABLED. It refuses to send the emails while any of
the 6 title images is missing from emails/assets (it prints their stems and
exits 1).
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

from scripts.send_proofs import PROOF_LINK_DISABLED, PROOF_TO, PUSH_PERSON_ID, _inert, _push_one, _smtp, _subscriptions

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'PUSH_PERSON_ID', 'plan', 'pushes', 'missing_titles', 'main']

_TOKEN_PATHS = (r'/alerts/confirm/[^"\'\s<>]+', r'/alerts/stop/[^"\'\s<>]+', r'/mentor\?invite=[^"\'\s<>]+',
                r'/i/[^"\'\s<>]+', r'/matches\?intro=[^"\'\s<>]+',
                # Your Ahavah answers not found until the light sign-in opens.
                r'/your-ahavah(?=["\'\s<>])')


def _inert_matchmaker_links(name: str, html: str) -> str:
    from service.config import API_BASE_URL, WEB_BASE_URL
    for base in {WEB_BASE_URL.rstrip('/'), API_BASE_URL.rstrip('/')}:
        for path in _TOKEN_PATHS:
            html = re.sub(re.escape(base) + path, PROOF_LINK_DISABLED, html)
    return _inert(name, html)


def plan() -> list[dict]:
    """Every proof email, built from sample data, in the export's order.
    Writes nothing and reads no switch."""
    from service.matchmaker import mail
    builders = [
        ('mm_alert_several', 'New members who fit, several (4.1)', mail.preview_alert_several),
        ('mm_alert_one', 'New members who fit, 1 (4.2)', mail.preview_alert_one),
        ('mm_alert_with_likes', 'With the likes waiting (4.3)', mail.preview_alert_with_likes),
        ('mm_visitor_confirm', 'Confirm your alert, to a visitor (4.4)', mail.preview_visitor_confirm),
        ('mm_visitor_alert', 'Someone who fits joined, to a visitor (4.5)', mail.preview_visitor_alert),
        ('mm_recommend', 'The recommendation, to the single (5.1)', mail.preview_recommend),
        ('mm_intro', 'An introduction, to each member (5.2)', mail.preview_intro),
        ('mm_mentor_invite', 'The mentor invitation (6.1)', mail.preview_mentor_invite),
        # Release 4's follow-ups (TEC-1845): with the "Your Ahavah" line.
        ('mm_mentor_invite_your_ahavah', 'The mentor invitation with the Your Ahavah line (1.7)',
         mail.preview_mentor_invite_your_ahavah),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert_matchmaker_links(name, html), from_addr=mail.FROM_ADDR))
    return out


def pushes() -> list[dict]:
    """The alert push, the introduction push and the introducer's, with
    sample names. Their links carry no ?src=, so a proof tap counts as
    nothing (as the question proofs')."""
    from service.matchmaker import mail
    out = [dict(mail.alert_push(2), kind='mm_alert'),
           dict(mail.intro_push(1, 'Hannah', 'Miriam'), kind='mm_intro'),
           dict(mail.introducer_push(1, 'Miriam', 'Daniel'), kind='mm_told')]
    return [dict(p, url=mail.without_src(p['url'])) for p in out]


def missing_titles() -> list[str]:
    """The stems of the title images (light or dark) not in emails/assets."""
    import emails.base as base
    from service.matchmaker.mail import TITLES
    return [stem for stem, _alt, _width in TITLES.values()
            if not ((base.ASSETS_DIR / f'{stem}.png').is_file()
                    and (base.ASSETS_DIR / f'{stem}-wht.png').is_file())]


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proof emails (default: dry run)')
    ap.add_argument('--push', action='store_true', help='send the proof pushes to the owner only')
    ap.add_argument('--only', default='', help='comma-separated proof names to send, and no others')
    a = ap.parse_args(argv)
    emails, ps = plan(), pushes()
    if a.only:
        wanted = {n.strip() for n in a.only.split(',') if n.strip()}
        unknown = wanted - {e['name'] for e in emails}
        if unknown:
            print('No such proof: ' + ', '.join(sorted(unknown)))
            sys.exit(2)
        emails = [e for e in emails if e['name'] in wanted]
        ps = []
    missing = missing_titles()
    print(f"{'SEND' if a.send or a.push else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}, "
          f"{len(ps)} proof pushes to account {PUSH_PERSON_ID}")
    for e in emails:
        print(f"  email  {e['name']:20s} {e['subject']}  ({e['label']})")
    for p in ps:
        print(f"  push   {p['kind']:20s} {p['title']}: {p['body']} -> {p['url']} [{p['tag']}]")
    if missing:
        print('Title images missing from emails/assets (light and -wht): ' + ', '.join(missing))
    if not (a.send or a.push):
        print('Nothing sent. Run with --send for the emails or --push for the pushes.')
        return
    if a.send:
        if missing:
            print('Not sending: a proof without its title image is not the email the owner would approve.')
            sys.exit(1)
        smtp = _smtp()
        for e in emails:
            mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO, from_addr=e['from_addr'])
            print(f"sent {e['name']} ({mid or 'no id'})")
    if a.push:
        subs = _subscriptions(PUSH_PERSON_ID)
        if not subs:
            print(f'account {PUSH_PERSON_ID} has no push subscription; no push sent')
        for p in ps:
            payload = dict(title=f"[Proof] {p['title']}", body=p['body'], url=p['url'], tag=p['tag'])
            for sub in subs:
                status = _push_one(sub, payload)
                print(f"pushed {p['kind']} ({'ok' if status is None else status})")


if __name__ == '__main__':
    main(sys.argv[1:])
