"""Friend joined (health review, 13 Oct 2026, finding 75).

The inviter was never told when a friend joined: finish-onboarding credits
them (30 days of Premium and 5 tokens) and discards the inviter it found.
Now the same transaction queues one email to the inviter. Never the friend's
name: whether to show it is left to the invite screen's own rule.

A person row exists only once onboarding is finished, so "joined" here
already means the friend finished their profile, which is when the reward
is credited. One email per friend (`friend_joined-<friend's person id>`).

Held: nothing is queued unless AHAVAH_FRIEND_JOINED_ENABLED is on. Runs
inside a member's sign-up, so it sits behind a savepoint and any failure is
rolled back and ignored: it can never undo the sign-up. Unsubscribe scope
`campaigns`, the referral programme's.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

import traceback
from typing import Optional

from emails.base import button, callout, chip, is_suppressed_send, render
from service.campaigns import campaign_unsubscribed, make_campaign_link
from service.campaigns import held
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'friend_joined'
SWITCH = 'friend_joined'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
TARGET = f"{WEB_BASE_URL}/invite"
SUBJECT = "Someone you invited has joined Ahavah"

_Q_INVITER = """
    SELECT id, email FROM person
     WHERE uuid::text = %(u)s AND activated AND deletion_requested_at IS NULL
"""


def friend_joined_html(cta_url: str, unsubscribe_url: str) -> str:
    body = f"""
{chip("Your invite")}

<div style="height:18px;line-height:18px;">&nbsp;</div>

{held.para("Someone you invited has joined Ahavah and finished their profile.")}

{held.para("Thank you. We have added 30 days to your Premium and 5 tokens to your account. 5 tokens buy a 30-minute boost on Discover.", bottom=24)}

{button("See your invites", cta_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Know someone else seeking marriage? Your invite link is on the same page.")}
"""
    return render(title=SUBJECT, preheader="Your invite worked. Here is what we added.",
                  body_html=body,
                  footer_html=held.footer("You're receiving this because someone joined through your invite link.",
                                          unsubscribe_url))


def _queue(tx, inviter_uuid: str, friend_person_id: int) -> Optional[int]:
    row = tx.execute(_Q_INVITER, dict(u=str(inviter_uuid))).fetchone()
    if not row or is_suppressed_send(row['email']):
        return None
    if campaign_unsubscribed(tx, row['id'], UNSUB_SCOPE):
        return None
    cid = f"{CAMPAIGN}-{friend_person_id}"
    if held.already_queued(tx, CAMPAIGN, cid, row['id']):
        return None
    cta = make_campaign_link(tx, CAMPAIGN, TARGET, row['id'])
    unsub = unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL)
    return held.queue(tx, campaign=CAMPAIGN, campaign_id=cid, person_id=row['id'],
                      email=row['email'], subject=SUBJECT, html=friend_joined_html(cta, unsub),
                      from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE, unsub_url=unsub)


def queue_for_inviter(tx, inviter_uuid: Optional[str], friend_person_id: int) -> Optional[int]:
    """Queue the email to the inviter, inside the caller's transaction.
    Returns the outbox row id, or None when nothing was queued (switch off,
    no inviter, unsubscribed, already queued, or a failure)."""
    if not inviter_uuid or not enabled(SWITCH):
        return None
    tx.execute('SAVEPOINT friend_joined')
    try:
        out = _queue(tx, inviter_uuid, friend_person_id)
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT friend_joined')
        print(traceback.format_exc())
        return None
    tx.execute('RELEASE SAVEPOINT friend_joined')
    return out


def preview(to: str) -> tuple[str, str]:
    """The proof. Nothing stored."""
    return SUBJECT, friend_joined_html(TARGET, unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
