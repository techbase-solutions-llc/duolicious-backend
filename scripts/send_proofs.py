"""Send the owner one proof of each email held in Wave 3, and one push of
each held push to his own account, so he can confirm them before any switch
is turned on (health review, 13 Oct 2026, global constraint: nothing new
reaches members before a proof reaches the owner).

    python -m scripts.send_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_proofs --send     # send the proofs

Run inside the api container (it needs the mailer settings and, for the
pushes, the VAPID keys).

What it does and does not do:

  * Emails go to PROOF_TO only, straight through the mailer, as the Growth
    tab's Preview button sends one. Never through the outbox, so nothing is
    queued, logged or capped against any member.
  * Every proof is built from sample data by each email's own preview
    builder: no member's counts, names or links. No campaign link, no
    Spotlight token and no send-log row is written. Buttons point straight at
    the page they lead to; the E1 confirm button points at a placeholder
    token, so it opens the confirm page's not-valid state.
  * Pushes go to the subscriptions of account PUSH_PERSON_ID only, sent
    directly, so not even that subscription's failure counter is touched.
  * No switch is read or changed: a proof goes out whichever way a switch is
    set, and turning one on stays a separate, deliberate act.
  * Every unsubscribe and "turn off" link points at PROOF_LINK_DISABLED. The
    proofs go to the owner's own address, so a real /u/<token> link would
    change his own settings if he clicked it. The words around each link
    are the real email's.
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

PROOF_TO = 'harrigan.tennyson@gmail.com'
PUSH_PERSON_ID = 18
PROOF_LINK_DISABLED = 'https://ahavah.app/proof-link-disabled'


def _inert(name: str, html: str) -> str:
    """The proof with each /u/<token> link replaced by PROOF_LINK_DISABLED.
    Refuses a proof that still carries one of the owner's unsubscribe
    tokens, whatever link it sits in."""
    from service.config import WEB_BASE_URL
    from service.unsubscribe import _SCOPES, make_token
    base = re.escape(WEB_BASE_URL.rstrip('/'))
    out = re.sub(base + r'/u/[^"\'\s<>]+', PROOF_LINK_DISABLED, html)
    if any(make_token(scope, PROOF_TO) in out for scope in _SCOPES):
        raise RuntimeError(f'the {name} proof still carries a live unsubscribe link')
    return out


def _emails() -> list[dict]:
    from emails import (friend_joined, likes_waiting_weekly, member_welcome, one_photo_nudge,
                        profile_views_weekly, referral_intro, reminders,
                        send_community_weekly, send_spotlight_resend)
    from emails.spotlight_card_ready import FROM_ADDR as E4_FROM, SUBJECT as E4_SUBJECT, card_ready_html
    from service.config import WEB_BASE_URL
    from service.unsubscribe import make_url

    def e4():
        return E4_SUBJECT, card_ready_html(
            'Miriam', 'member of the week', f"{WEB_BASE_URL}/spotlight/card/proof", 7,
            make_url('campaigns', PROOF_TO, WEB_BASE_URL), new_copy=True)

    builders = [
        ('likes_waiting', 'Likes waiting, weekly (57, 64)', likes_waiting_weekly.preview, likes_waiting_weekly.FROM_ADDR),
        ('match_reminder', 'Match reminder (61)', reminders.preview_match, reminders.FROM_ADDR),
        ('message_reminder', 'Message reminder (61)', reminders.preview_message, reminders.FROM_ADDR),
        ('profile_views', 'Profile views, weekly (65)', profile_views_weekly.preview, profile_views_weekly.FROM_ADDR),
        ('one_photo', 'Add a second photo (38)', one_photo_nudge.preview, one_photo_nudge.FROM_ADDR),
        ('e2_personal', 'Weekly email with the personal line and invite link (60, 76)',
         send_community_weekly.preview_personal, send_community_weekly.FROM_ADDR),
        ('referral_member', 'Referral email for members (68)', referral_intro.preview_member, referral_intro.FROM_ADDR),
        ('friend_joined', 'Friend joined (75)', friend_joined.preview, friend_joined.FROM_ADDR),
        ('e1_spotlight', 'Spotlight announcement and its resend, new copy (79, 80, 82)',
         send_spotlight_resend.preview, send_spotlight_resend.FROM_ADDR),
        ('e4_card_ready', 'Spotlight card ready, new copy (79, 82)', lambda to: e4(), E4_FROM),
        ('e2_gatherings', 'Weekly email with Gatherings near you (events item 20)',
         send_community_weekly.preview_gatherings, send_community_weekly.FROM_ADDR),
        ('welcome_gatherings', 'Member welcome with the gatherings mention (events item 20)',
         member_welcome.preview_welcome_gatherings, member_welcome.FROM_ADDR),
    ]
    waiting = missing_titles()
    out = []
    for name, label, build, from_addr in builders:
        if waiting and name in _GATHERINGS_PROOFS:
            continue
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f"[PROOF] {subject}",
                        html=_inert(name, html), from_addr=from_addr))
    return out


# The title images of the gatherings round (handoff 20). A proof without its
# title is not the email the owner would approve, so these 2 wait for them.
_GATHERINGS_PROOFS = ('e2_gatherings', 'welcome_gatherings')
GATHERINGS_TITLES = ('subhead-gatherings-near', 'subhead-gather-community')


def missing_titles() -> list[str]:
    """The stems of the gatherings title images (light or dark) not in
    emails/assets."""
    from emails import base
    return [stem for stem in GATHERINGS_TITLES
            if not ((base.ASSETS_DIR / f'{stem}.png').is_file()
                    and (base.ASSETS_DIR / f'{stem}-wht.png').is_file())]


def _pushes() -> list[dict]:
    from emails.reminders import PUSH_PROOFS
    return [dict(p) for p in PUSH_PROOFS]


def plan() -> tuple[list[dict], list[dict]]:
    """Every proof email, built, and every proof push. Writes nothing."""
    return _emails(), _pushes()


def _smtp():
    from smtp import make_aws_smtp
    return make_aws_smtp()


def _subscriptions(person_id: int) -> list[dict]:
    from database import api_tx
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscription WHERE person_id = %(p)s",
            dict(p=person_id)).fetchall()]


def _push_one(sub: dict, payload: dict) -> Optional[int]:
    """One push to one subscription, with nothing written back."""
    from service.notifications import PUSH_ENABLED, _send_one
    if not PUSH_ENABLED:
        raise RuntimeError('VAPID keys are not set in this container')
    return _send_one(sub['endpoint'], sub['p256dh'], sub['auth'], payload)


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails, pushes = plan()
    mode = 'SEND' if a.send else 'DRY RUN'
    waiting = missing_titles()
    if waiting:
        print(f"waiting for title images: {', '.join(waiting)}")
    print(f"{mode}: {len(emails)} proof emails to {PROOF_TO}, "
          f"{len(pushes)} proof pushes to account {PUSH_PERSON_ID}")
    for e in emails:
        print(f"  email  {e['name']:17s} {e['subject']}  ({e['label']})")
    for p in pushes:
        print(f"  push   {p['kind']:17s} {p['title']}: {p['body']} -> {p['url']}")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO,
                        from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")
    subs = _subscriptions(PUSH_PERSON_ID)
    if not subs:
        print(f"account {PUSH_PERSON_ID} has no push subscription; no push sent")
    for p in pushes:
        payload = dict(title=f"[Proof] {p['title']}", body=p['body'], url=p['url'])
        for sub in subs:
            status = _push_one(sub, payload)
            print(f"pushed {p['kind']} ({'ok' if status is None else status})")


if __name__ == '__main__':
    main(sys.argv[1:])
