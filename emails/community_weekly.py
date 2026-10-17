"""E2 weekly community email (spec 3.5). Replaces emails/digest.py.
Copy rules: NO em dashes. Sentence case."""
from __future__ import annotations

import html as _html
from typing import Optional
from service.config import EMAIL_DOMAIN
from service.spotlight.country import display_country
from emails.base import render, button, chip, title_image, callout, INK_SOFT, MUTED, SANS

FROM_ADDR = f"support@{EMAIL_DOMAIN}"
SUBJECT = "This week on Ahavah"

def _esc(value) -> str:
    """Member-supplied text (names, ages, countries) goes into HTML email and
    into an alt="..." attribute, so escape quotes as well as angle brackets.
    Same convention as emails/feedback.py and emails/marriage_checklist.py."""
    return _html.escape(str(value), quote=True)


def _esc_country(value) -> str:
    """`person.country` is an alpha-2 code, so "in BB" is what the raw column
    would put in a member's inbox. Named here rather than in the query that
    fetches it: the preview path and the real send both come through this
    module, so neither can miss it."""
    return _esc(display_country(value))


def _esc_https(url: str, field: str) -> str:
    """Spotlight image and post URLs land in href/src. Pin them to https so a
    javascript: or data: URL can never be curated into a card, then escape."""
    u = str(url or '')
    if not u.startswith('https://'):
        raise ValueError(f"spotlight {field} must be an https URL")
    return _html.escape(u, quote=True)


def _spotlight_block(sp: dict) -> str:
    first_name = _esc(sp['first_name'])
    age = _esc(sp['age'])
    country = _esc_country(sp['country'])
    post_url = _esc_https(sp['post_url'], 'post_url')
    image_url = _esc_https(sp['image_url'], 'image_url')
    return f"""
<p class="e-text" style="margin:0 0 8px;font-family:{SANS};font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};font-weight:700;">Member of the week</p>
<a href="{post_url}" style="text-decoration:none;">
  <img src="{image_url}" alt="{first_name}, {age}, {country}" width="520" style="display:block;width:100%;max-width:520px;border-radius:16px;margin:0 0 10px;" />
</a>
<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">{first_name}, {age} <span style="color:{MUTED};">in {country}</span></p>
"""

def _newcomers_block(rows: list[dict], invite_below: bool = False) -> str:
    if not rows:
        # With the member's own invite link further down (finding 76) the
        # pointer to the profile would only repeat it.
        tail = '' if invite_below else ' Know someone who belongs here? Your invite link is in your profile.'
        return f'<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">No new members this week.{tail}</p>'
    items = "".join(f'<li style="margin:0 0 6px;">{_esc(r["first_name"])}' + (f' <span style="color:{MUTED};">in {_esc_country(r["country"])}</span>' if r.get('country') else '') + '</li>' for r in rows)
    return f'<p class="e-text" style="margin:0 0 8px;font-family:{SANS};font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};font-weight:700;">New this week</p><ul style="margin:0 0 20px;padding-left:20px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">{items}</ul>'

def _safe_spotlight_block(spotlight: Optional[dict]) -> str:
    """Render the spotlight card, or fall back to no spotlight at all if its
    fields fail validation (e.g. a curated URL that is not https).

    _spotlight_block/_esc_https deliberately still raise on a bad URL -- the
    validation itself must stay -- but community_weekly_html() is called once
    per recipient inside service/campaigns/runner.py's send loop, and an
    uncaught exception there aborts the run at that recipient (see
    run_campaign: a build() failure returns early with every remaining
    recipient unsent). One bad curated post must not do that to the whole
    weekly send, so render the newcomers-only variant instead and log a
    warning for whoever curates the next one to see."""
    if not spotlight:
        return ''
    try:
        return _spotlight_block(spotlight)
    except ValueError as e:
        print(f"community_weekly: dropping invalid spotlight ({e})")
        return ''


def _personal_block(line: Optional[str]) -> str:
    """The reader's own reason to come back (finding 60). Built by
    send_community_weekly from counts only, never member text."""
    if not line:
        return ''
    return f'<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:18px;line-height:1.5;color:{INK_SOFT};font-weight:700;">{line}</p>'


def _question_block(line: Optional[str]) -> str:
    """This week's quick question (TEC-1845), held behind
    AHAVAH_E2_QUESTION_LINE_ENABLED. Built from the question bank, never
    member text; escaped all the same. It is element text, not an attribute,
    so quotes stay as written ("This week's question")."""
    if not line:
        return ''
    return (f'<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;'
            f'line-height:1.55;color:{INK_SOFT};">{_html.escape(line, quote=False)}</p>')


def _invite_block(invite_url: Optional[str]) -> str:
    """The member's own invite link, every week (finding 76)."""
    if not invite_url:
        return ''
    return f"""
<div style="height:24px;line-height:24px;">&nbsp;</div>
<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">Know a Torah-observant single who belongs here? Send them your own invite link.</p>
{button("Share your invite link", invite_url, variant="dark")}
"""


def community_weekly_html(new_members: list[dict], total_members: int, spotlight: Optional[dict], cta_url: str, unsubscribe_url: str,
                          *, personal_line: Optional[str] = None, invite_url: Optional[str] = None,
                          cta_label: str = "Open Discover", question_line: Optional[str] = None) -> str:
    """`personal_line`, `invite_url` and `cta_label` are the held personal
    parts (AHAVAH_E2_PERSONAL_ENABLED); `question_line` is this week's quick
    question (AHAVAH_E2_QUESTION_LINE_ENABLED); left out, the email is as it
    was."""
    body = f"""
{chip("Community")}

{title_image("title-community.png", "title-community-wht.png", "This week on Ahavah.", 460)}

{_personal_block(personal_line)}

{_question_block(question_line)}

{_safe_spotlight_block(spotlight)}

{_newcomers_block(new_members, invite_below=bool(invite_url))}

<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;line-height:1.55;color:{INK_SOFT};">
  The community is now <strong>{total_members} members</strong> across borders.
</p>

{button(cta_label, cta_url)}

{_invite_block(invite_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Want to be featured? Turn on Spotlight under Settings, Privacy.")}
"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving the weekly community email as a member of Ahavah.
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Stop the weekly email</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
</div>
"""
    return render(title=SUBJECT, preheader="New members, community size, and this week's spotlight.", body_html=body, footer_html=footer)
