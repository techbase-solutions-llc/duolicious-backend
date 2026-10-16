"""The owner's personal note to the Spotlight candidates (health review,
13 Oct 2026, finding 85). Wording approved by the owner on 13 Oct 2026, with
one change made since to match the live Spotlight copy: "your main profile
photo" in place of "one photo of you". Change it only with his approval.

It reads as a personal email from him, like the warm leads note
(emails/warm_leads_note.py): the standard brand shell, whose dark band
carries the logo, with plain paragraphs and no title image, chip or button.
The guardrails the owner agreed (finding 87) hold: one honest invitation
with an easy no, and no reward for saying yes.

`first_name` is None when the member's name is empty, and the greeting is
then just "Shalom,".
"""
from __future__ import annotations

import html as _html

from emails.base import INK_SOFT, MUTED, SANS, render

SUBJECT = "Would you help us introduce Ahavah?"

PREHEADER = "Nothing is posted unless you approve that exact card."

_P = f"margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};"

PARAGRAPHS = (
    "We are starting to introduce a few members on Ahavah’s Facebook and Instagram, "
    "so believers who have not heard of us can see real people here. Each post is your main "
    "profile photo, your first name, age and country, and nothing else.",
    "Nothing is posted unless you approve that exact card, and you can say no to any card or "
    "switch it off at any time. If you would rather not, that is completely fine and changes "
    "nothing for you.",
    "If you are willing, turn on Spotlight in Settings, under Privacy, and we will send you a "
    "card to look at first.",
)


def _greeting(first_name: str | None) -> str:
    return f"Shalom {first_name}," if first_name else "Shalom,"


def note_html(first_name: str | None, unsubscribe_url: str) -> str:
    greeting = _html.escape(_greeting(first_name))
    paras = "\n".join(f'<p class="e-text" style="{_P}">{_html.escape(p)}</p>' for p in PARAGRAPHS)
    unsub = _html.escape(unsubscribe_url, quote=True)
    body = f"""
<p class="e-text" style="{_P}">{greeting}</p>
{paras}
<p class="e-text" style="{_P}margin-bottom:0;">Ehud</p>
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving this because you're a member of Ahavah.
<div style="margin-top:14px;">
  <a href="{unsub}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Unsubscribe</a>
</div>
"""
    return render(title=_html.escape(SUBJECT), preheader=PREHEADER, body_html=body, footer_html=footer)


def note_text(first_name: str | None, unsubscribe_url: str) -> str:
    blocks = [
        _greeting(first_name),
        *PARAGRAPHS,
        "Ehud",
        f"Unsubscribe: {unsubscribe_url}",
    ]
    return "\n\n".join(blocks) + "\n"
