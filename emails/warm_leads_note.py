"""The owner's personal note to the warm leads (health review, 13 Oct 2026,
finding 48). Wording approved by the owner on 13 Oct 2026; change it only
with his approval.

It reads as a personal email from him, not a campaign: plain paragraphs,
no title image, chip or button. The owner then asked for "some minimal
branding" (13 Oct 2026), so it sits in the standard brand shell, whose dark
band carries the logo, with the usual footer.

`first_name` is None when the lead's stored answers hold no name, and the
greeting is then just "Shalom,". `n` is the member count at send time.
"""
from __future__ import annotations

import html as _html

from emails.base import INK, INK_SOFT, MUTED, SANS, render

SUBJECT = "A quick question from Ehud"
SITE = "https://ahavah.app"

PREHEADER = "A one-line reply is plenty."

_P = f"margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};"


def _greeting(first_name: str | None) -> str:
    return f"Shalom {first_name}," if first_name else "Shalom,"


def _paragraphs(n: int) -> list[str]:
    return [
        "You put your name down for Ahavah earlier this year. The app has been "
        f"open for a few months now, and {n} believers have joined, most of them "
        "in the United States.",
        "I noticed you never made a profile, and I would like to know why. Was it "
        "the timing, something on the sign-up screens, or did Ahavah not look like "
        "what you were hoping for? A one-line reply is plenty, and I read every one.",
    ]


def note_html(first_name: str | None, n: int, unsubscribe_url: str) -> str:
    greeting = _html.escape(_greeting(first_name))
    paras = "\n".join(f'<p class="e-text" style="{_P}">{_html.escape(p)}</p>' for p in _paragraphs(n))
    unsub = _html.escape(unsubscribe_url, quote=True)
    body = f"""
<p class="e-text" style="{_P}">{greeting}</p>
{paras}
<p class="e-text" style="{_P}">If you would like to look again, it is at <a href="{SITE}" style="color:{INK};font-weight:600;">ahavah.app</a>.</p>
<p class="e-text" style="{_P}margin-bottom:0;">Ehud</p>
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving this because you put your name down for Ahavah.
<div style="margin-top:14px;">
  <a href="{unsub}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Unsubscribe</a>
</div>
"""
    return render(title=_html.escape(SUBJECT), preheader=PREHEADER, body_html=body, footer_html=footer)


def note_text(first_name: str | None, n: int, unsubscribe_url: str) -> str:
    blocks = [
        _greeting(first_name),
        *_paragraphs(n),
        "If you would like to look again, it is at ahavah.app.",
        "Ehud",
        f"Unsubscribe: {unsubscribe_url}",
    ]
    return "\n\n".join(blocks) + "\n"
