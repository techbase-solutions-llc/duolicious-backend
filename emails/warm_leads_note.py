"""The owner's personal note to the warm leads (health review, 13 Oct 2026,
finding 48). Wording approved by the owner on 13 Oct 2026; change it only
with his approval.

This is deliberately NOT on the brand shell in emails/base.py. The owner
asked for a note that reads like a personal email from him, not a campaign:
plain paragraphs, no logo band, no title image, no button, and a small
footer that carries only the unsubscribe link. tests/
test_email_templates_use_the_brand_shell.py names this file as the one
exception, with that reason.

`first_name` is None when the lead's stored answers hold no name, and the
greeting is then just "Shalom,". `n` is the member count at send time.
"""
from __future__ import annotations

import html as _html

SUBJECT = "A quick question from Ehud"
SITE = "https://ahavah.app"

# Readable in light and dark clients alike: no background colour anywhere,
# and the body text takes the client's own colour.
_FONT = "-apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
_P = "margin:0 0 16px;"
_FOOT = "margin:32px 0 0;font-size:12px;line-height:1.5;color:#8a8a8a;"


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
    paras = "\n".join(f'<p style="{_P}">{_html.escape(p)}</p>' for p in _paragraphs(n))
    unsub = _html.escape(unsubscribe_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_html.escape(SUBJECT)}</title>
</head>
<body style="margin:0;padding:0;">
<div style="max-width:560px;margin:0 auto;padding:24px 16px;font-family:{_FONT};font-size:16px;line-height:1.6;">
<p style="{_P}">{greeting}</p>
{paras}
<p style="{_P}">If you would like to look again, it is at <a href="{SITE}">ahavah.app</a>.</p>
<p style="{_P}">Ehud</p>
<p style="{_FOOT}"><a href="{unsub}" style="color:#8a8a8a;">Unsubscribe</a></p>
</div>
</body>
</html>"""


def note_text(first_name: str | None, n: int, unsubscribe_url: str) -> str:
    blocks = [
        _greeting(first_name),
        *_paragraphs(n),
        "If you would like to look again, it is at ahavah.app.",
        "Ehud",
        f"Unsubscribe: {unsubscribe_url}",
    ]
    return "\n\n".join(blocks) + "\n"
