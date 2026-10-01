"""Evergreen member welcome: fires once per member, right after the
early-member Premium grant lands at finish-onboarding.

The trigger latch is the grant itself: service/person calls
send_member_welcome_async ONLY when grant_founding_member_if_eligible
returned True, which happens exactly once per member (replays are full
no-ops). So this email can never double-send.

All personalized facts (Premium expiry, referral code) are read live
from the database inside the send thread, never passed from the
request path, so the copy cannot race the grant transaction.

Copy rules: NO em dashes. Sentence case. Not wordy.
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime

from database import api_tx
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from emails.base import (
    render,
    button,
    chip,
    title_image,
    callout,
    is_suppressed_send,
    INK_SOFT,
    MUTED,
    SANS,
)
from emails.premium_referral import _referral_block, _fmt_date

FROM_ADDR = f"support@{EMAIL_DOMAIN}"

SUBJECT = "Welcome to Ahavah. Your Premium is live"

_Q_MEMBER = """
    SELECT id, name, subscription_expires_at, referral_code
      FROM person
     WHERE email = %(email)s AND activated
"""


def member_welcome_html(
    premium_until: datetime,
    invite_url: str,
    unsubscribe_url: str,
) -> str:
    body = f"""
{chip("Welcome")}

{title_image("title-member-welcome.png", "title-member-welcome-wht.png", "Welcome to the family.", 512)}

<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  You're in. Ahavah is matchmaking built by and for Torah-observant
  believers, and every early member starts with 6 months of
  Premium free. Yours is already live: it runs until
  <strong>{_fmt_date(premium_until)}</strong>, and 30 tokens are in
  your wallet for super likes, boosts and more.
</p>

{_referral_block(invite_url)}

{button("Start discovering", f"{WEB_BASE_URL}/discover")}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Tip: members who add photos and complete their profile get seen first. The map shows the whole community.")}
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving this because you just joined Ahavah.
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Unsubscribe</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/privacy" style="color:{MUTED};font-weight:600;text-decoration:underline;">Privacy</a>
</div>
"""
    return render(
        title=SUBJECT,
        preheader="6 months of Premium and 30 tokens, already on your account.",
        body_html=body,
        footer_html=footer,
    )


def send_member_welcome(email: str) -> bool:
    """Queue the welcome through the durable outbox. Reads the member's live
    Premium expiry and referral code; returns False (nothing queued) if the
    member is missing, suppressed, not yet fully granted (no expiry / no
    code), or already welcomed.

    Until 1 Oct 2026 this spoke to SMTP directly from a thread and kept no
    record, so nobody could say whether a member's welcome had gone. The
    outbox drain writes email_send_log on acceptance (campaign `welcome`),
    which is what Growth > Emails reads (TEC-1613). Exempt from the frequency
    cap: a welcome is the one email a new member is owed whatever else went
    out that week."""
    if is_suppressed_send(email):
        return False

    from service.campaigns import outbox
    from service.unsubscribe import make_url as unsub_url

    with api_tx() as tx:
        row = tx.execute(_Q_MEMBER, dict(email=email)).fetchone()
        if not row or not row['subscription_expires_at'] or not row['referral_code']:
            return False
        unsub = unsub_url('notifications', email, WEB_BASE_URL)
        row_id = outbox.enqueue(
            tx, campaign='welcome', campaign_id=f"welcome-{row['id']}", person_id=row['id'],
            email=email, subject=SUBJECT,
            html=member_welcome_html(
                row['subscription_expires_at'],
                f"https://ahavah.app/i/{row['referral_code']}",
                unsub,
            ),
            from_addr=FROM_ADDR, unsub_scope='notifications',
            list_unsubscribe=f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{unsub}>",
            exempt=True)
    return row_id is not None


def send_member_welcome_async(email: str) -> None:
    """Fire-and-forget from the /finish-onboarding path; failures are
    swallowed (the member is already onboarded, the email is a nicety)."""
    def _go() -> None:
        try:
            send_member_welcome(email)
        except Exception:
            print(traceback.format_exc())

    threading.Thread(target=_go, daemon=True).start()
