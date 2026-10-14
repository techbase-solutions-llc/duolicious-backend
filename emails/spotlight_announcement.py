"""E1 Spotlight announcement + opt-in (spec 3.5). Canonical shell.
Copy rules: NO em dashes. Sentence case."""
from __future__ import annotations

from service.config import EMAIL_DOMAIN
from emails.base import render, button, chip, title_image, callout, INK_SOFT, MUTED, SANS
from service.campaigns.switches import enabled

FROM_ADDR = f"support@{EMAIL_DOMAIN}"
SUBJECT = "Meet Spotlight, a new way to be seen on Ahavah"

# The live copy, and the copy that matches the web lane's Spotlight strings
# (health review, 13 Oct 2026, findings 79 and 82: a card shows the main
# profile photo, never a photo the member picks). The new copy is held behind
# AHAVAH_SPOTLIGHT_COPY_ENABLED until the owner confirms the proof; the E1
# resend (emails/send_spotlight_resend.py) always uses it.
_OLD_PARAGRAPHS = (
    "Spotlight puts real members in front of the wider community: a welcome "
    "when you join, a member of the week, and the occasional highlight, on "
    "the Ahavah Facebook page and Instagram and in the weekly community email.",
    "It is opt in. If you join, we share only your first name, age, country "
    "and one photo you choose, and you approve every card before it goes out. "
    "You can turn it off any time in settings.",
)
_NEW_PARAGRAPHS = (
    "Spotlight helps believers who have not heard of Ahavah see real people "
    "here: a welcome when you join, a member of the week and the occasional "
    "highlight, on the Ahavah Facebook page and Instagram and in the weekly "
    "community email.",
    "It is opt in. Each card shows your main profile photo, first name, age "
    "and country, and nothing else. Nothing is posted until you approve that "
    "exact card. Say no to any card, or turn Spotlight off any time in "
    "Settings, Privacy.",
)
_OLD_PREHEADER = "Opt in to be featured. First name, age, country, one photo you choose."
_NEW_PREHEADER = "Opt in to be featured. Your main profile photo, first name, age and country."


def spotlight_announcement_html(confirm_url: str, settings_url: str, unsubscribe_url: str,
                                *, new_copy: bool | None = None) -> str:
    """`new_copy` None follows AHAVAH_SPOTLIGHT_COPY_ENABLED; the resend
    passes True."""
    if new_copy is None:
        new_copy = enabled('spotlight_copy')
    first, second = _NEW_PARAGRAPHS if new_copy else _OLD_PARAGRAPHS
    body = f"""
{chip("New on Ahavah")}

{title_image("title-spotlight.png", "title-spotlight-wht.png", "Meet Spotlight.", 430)}

<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  {first}
</p>

<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  {second}
</p>

{button("Feature me in Spotlight", confirm_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Not for you? Nothing changes. Your profile stays exactly as private as it is today.")}

<p class="e-text" style="margin:16px 0 0;font-family:{SANS};font-size:15px;line-height:1.5;color:{MUTED};">
  You can also switch it on later under <a href="{settings_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Settings, Privacy</a>.
</p>
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving this because you're a member of Ahavah.
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Unsubscribe</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/privacy" style="color:{MUTED};font-weight:600;text-decoration:underline;">Privacy</a>
</div>
"""
    return render(title=SUBJECT, preheader=_NEW_PREHEADER if new_copy else _OLD_PREHEADER,
                  body_html=body, footer_html=footer)
