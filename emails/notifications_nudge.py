"""E6, turn on notifications (TEC-1607). Canonical shell.

To an active member who has no push subscription. One idea, one button: we
can tell you the moment someone likes you or writes to you, and here is the
tap that turns it on. The iPhone line is there because on iOS push only
works from a home screen install, and a member who taps the button in
Safari and sees nothing happen will not try twice.

Copy rules: NO em dashes. Sentence case. Torah-observant believers, never
Jewish framing.
"""
from __future__ import annotations

import html as _html

from service.config import EMAIL_DOMAIN
from emails.base import render, button, chip, callout, title_image, INK_SOFT, MUTED, SANS

FROM_ADDR = f"support@{EMAIL_DOMAIN}"
SUBJECT = "Hear about it the moment it happens"
PREHEADER = "Notifications are off for your account. One tap turns them on."


def notifications_nudge_html(first_name: str, settings_url: str, unsubscribe_url: str) -> str:
    name = _html.escape(str(first_name or 'there'), quote=True)
    body = f"""
{chip("Notifications")}

{title_image("title-note.png", "title-note-wht.png", "A note from Ahavah.", 460)}

<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  {name}, when someone likes you or writes to you on Ahavah, we can tell you
  straight away, even when the app is closed.
</p>

<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  Notifications are off for your account at the moment. One tap turns them
  on, and you choose what you hear about: matches, messages, likes.
</p>

{button("Turn on notifications", settings_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("On an iPhone, add Ahavah to your home screen first. Notifications only work from there.")}
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving this because you're a member of Ahavah.
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Unsubscribe</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
</div>
"""
    return render(title=SUBJECT, preheader=PREHEADER, body_html=body, footer_html=footer)
