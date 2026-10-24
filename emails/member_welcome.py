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

import html as _html
import threading
import traceback
from datetime import datetime, timezone
from typing import Optional

from database import api_tx
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from emails.base import (
    render,
    button,
    chip,
    title_image,
    callout,
    is_suppressed_send,
    INDIGO,
    INK,
    INK_SOFT,
    MUTED,
    SANS,
)
from emails.premium_referral import _referral_block, _fmt_date
from emails import gatherings_section

FROM_ADDR = f"support@{EMAIL_DOMAIN}"

SUBJECT = "Welcome to Ahavah. Your Premium is live"

_Q_MEMBER = """
    SELECT id, name, subscription_expires_at, referral_code, country
      FROM person
     WHERE email = %(email)s AND activated
"""


# The gatherings mention (TEC-1845), M.1 of Ahavah Gatherings in Member
# Emails.html: its subhead at its natural CSS width (handoff 20, titles.json).
_GATHER_TITLE = ("subhead-gather-community.png", "subhead-gather-community-wht.png",
                 "Gather with the community.", 252)  # NEW LINE
# The owner's wording, copy pass of 23 Oct 2026 (file 20, row 4).
GATHER_LISTS = ("Ahavah lists gatherings in person and online, hosted by assemblies, "  # NEW LINE
                "fellowship leaders, ministries and Ahavah itself.")
# True only while an online gathering is listed (copy pass claim 9), so the
# line is left out when none is.
GATHER_ONLINE = "Online gatherings are open to you wherever you live."  # NEW LINE
GATHER_LINK = "See gatherings near you"


def _gatherings_mention(events_url: str, online_listed: bool) -> str:
    """M.1: the subhead image, its lines and a text link padded to a 44 px
    tap area. No live list and no count: the welcome is sent once, at
    sign-up, and promises the list, never one nearby; it promises online
    gatherings only while one is listed. The lines are at the body's
    17 px, so a phone shows them at the body's 12 px. Wrapped in
    gatherings_section's markers, so the drain can take it out of a
    welcome already queued once the switch is off."""
    href = _html.escape(events_url, quote=True)
    lines = (GATHER_LISTS, GATHER_ONLINE) if online_listed else (GATHER_LISTS,)
    paras = ''.join(
        f'<p class="e-strong" style="margin:0 0 12px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK};">{line}</p>'
        for line in lines)
    return gatherings_section.mark(f"""
<div style="height:6px;line-height:6px;">&nbsp;</div>
{title_image(*_GATHER_TITLE)}
{paras}
<p style="margin:0 0 12px;font-family:{SANS};">
  <a class="e-link" href="{href}" style="display:inline-block;padding:12px 0;font-size:15px;line-height:20px;color:{INDIGO};font-weight:700;text-decoration:underline;">{GATHER_LINK}</a>
</p>
""")


def member_welcome_html(
    premium_until: datetime,
    invite_url: str,
    unsubscribe_url: str,
    *,
    events_url: Optional[str] = None,
    online_listed: bool = False,
) -> str:
    """`events_url` is the gatherings mention (AHAVAH_WELCOME_GATHERINGS_ENABLED),
    placed after the existing welcome content as M.1 draws it; left out, the
    welcome is as it was. `online_listed` adds its line about online
    gatherings, said only while one is listed."""
    mention = _gatherings_mention(events_url, online_listed) if events_url else ''
    body = f"""
{chip("Welcome")}

{title_image("title-member-welcome.png", "title-member-welcome-wht.png", "Welcome to the family.", 276)}

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
{mention}"""
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


def _events_link(tx, row) -> Optional[str]:
    """The mention's link, a welcome campaign link to /events in the
    member's region, minted only while the switch and the events list are
    on. A member with no country is sent to the online gatherings, /events
    on its Online pill (owner's answer of 24 Oct 2026, decision 4
    restated). Kind 'welcome', the campaign key the welcome's send log and
    Growth > Emails already use."""
    from service.events import member_email_on
    if not member_email_on('welcome_gatherings'):
        return None
    from service.campaigns import make_campaign_link
    from service.matchmaker.regions import region_of
    region = region_of(row['country']) or 'online'
    target = f"{WEB_BASE_URL}/events?region={region}"
    return make_campaign_link(tx, 'welcome', target, row['id'])


def preview_welcome_gatherings(to: str) -> tuple[str, str]:
    """The proof of the welcome with its gatherings mention: a sample Premium
    date and code, the link straight to North America's list. Writes nothing."""
    from datetime import timedelta
    from service.unsubscribe import make_url as unsub_url
    until = datetime.now(timezone.utc) + timedelta(days=183)
    return SUBJECT, member_welcome_html(
        until, "https://ahavah.app/i/MIRIAM7K", unsub_url('campaigns', to, WEB_BASE_URL),
        events_url=f"{WEB_BASE_URL}/events?region=north-america", online_listed=True)


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
        # The campaigns scope (finding 62): leaving the welcome must not
        # silence match and message emails.
        unsub = unsub_url('campaigns', email, WEB_BASE_URL)
        campaign_id = f"welcome-{row['id']}"
        # A member already welcomed: return before minting the mention's
        # link, so a repeat call (send_member_welcome.py --send loops a
        # window) stores no link for an email that is never sent.
        if tx.execute("SELECT 1 FROM email_outbox WHERE campaign = 'welcome' AND campaign_id = %(c)s "
                      "AND person_id = %(p)s", dict(c=campaign_id, p=row['id'])).fetchone():
            return False
        events_url = _events_link(tx, row)
        online = False
        if events_url:
            from service.events import public
            online = public.online_listed(tx, now=datetime.now(timezone.utc))
        row_id = outbox.enqueue(
            tx, campaign='welcome', campaign_id=campaign_id, person_id=row['id'],
            email=email, subject=SUBJECT,
            html=member_welcome_html(
                row['subscription_expires_at'],
                f"https://ahavah.app/i/{row['referral_code']}",
                unsub,
                events_url=events_url,
                online_listed=online,
            ),
            from_addr=FROM_ADDR, unsub_scope='campaigns',
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
