"""E2 weekly community email (spec 3.5). Replaces emails/digest.py.
Copy rules: NO em dashes. Sentence case."""
from __future__ import annotations

import html as _html
from typing import Callable, Optional
from service.config import EMAIL_DOMAIN
from service.spotlight.country import display_country
from emails.base import render, button, chip, title_image, callout, INK, INK_SOFT, INDIGO, LIME, MUTED, PANEL, SANS

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


# PENDING DESIGN: the subhead image and its natural width come back from
# the Claude Design round (gatherings in the member emails, Task 1). Until
# then the file is missing from emails/assets/, asset_src falls back to the
# public url, and the switch stays off. 280 is the brief's wrap width.
_GATHERINGS_TITLE = ("subhead-gatherings.png", "subhead-gatherings-wht.png", "Gatherings near you.", 280)


def _gathering_card(g: dict, href: str) -> str:
    """One gathering as a table row (frame 4.2): the date block, the title,
    the city or "Online", the organiser and "Ahavah will be there". Every
    organiser field is escaped. Raises on a card with no date (a zone the
    server does not know) or a missing field; the caller drops that card.

    PENDING DESIGN: the date block's sizes and the card's spacing follow
    frame 4.2 with the day number held at 18 px (the frame types it at 20,
    which the phone check rejects); Task 1 returns the email-safe block."""
    day_name, day, month = g['date']
    if g['mode'] == 'online':
        place = 'Online'
    else:
        place = ', '.join(_esc(v) for v in (g.get('city'), g.get('country')) if v)
    link = _html.escape(href, quote=True)
    chip_html = ''
    if g.get('ahavah_attending'):
        chip_html = (f'<span style="display:inline-block;margin-top:6px;padding:3px 9px;border-radius:999px;'
                     f'background:{LIME};color:{INK};font-family:{SANS};font-size:12px;font-weight:700;">'
                     f'Ahavah will be there</span>')
    return f"""
<tr><td style="padding:0 0 10px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;background:{PANEL};border-radius:14px;">
    <tr>
      <td width="56" valign="top" style="width:56px;padding:12px 0 12px 12px;">
        <a href="{link}" style="display:block;text-decoration:none;text-align:center;border-radius:10px;background:#EDE8FE;padding:6px 0;font-family:{SANS};color:{INDIGO};">
          <span style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">{_esc(day_name)}</span>
          <span style="display:block;font-size:18px;line-height:1.1;font-weight:800;">{_esc(day)}</span>
          <span style="display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">{_esc(month)}</span>
        </a>
      </td>
      <td valign="top" style="padding:12px;font-family:{SANS};">
        <a href="{link}" style="color:{INK};text-decoration:none;font-size:15px;line-height:1.35;font-weight:700;">{_esc(g['title'])}</a>
        <div style="font-size:13px;line-height:1.45;color:{MUTED};margin-top:2px;">{place}</div>
        <div style="font-size:13px;line-height:1.45;color:{MUTED};">{_esc(g['organiser']['name'])}</div>
        {chip_html}
      </td>
    </tr>
  </table>
</td></tr>"""


def _gatherings_block(gatherings: list[dict], online_only: bool, see_all_url: str,
                      card_url: Callable[[str], str]) -> str:
    """Gatherings near you (TEC-1845, frames 4.2 to 4.5), held behind
    AHAVAH_E2_GATHERINGS_ENABLED. Left out when the member has none (4.4,
    4.5). Built once per recipient inside run_campaign's loop, so a card
    that raises is dropped with a warning, as _safe_spotlight_block does,
    and never the email."""
    cards = []
    for g in gatherings or []:
        try:
            cards.append(_gathering_card(g, card_url(g['slug'])))
        except Exception as e:  # one card, never the send
            print(f"community_weekly: dropping gathering {g.get('slug')!r} ({e!r})")
    if not cards:
        return ''
    # Copy 1.5 of the marketing pages, for a member with a region whose
    # every card is online (owner decision 5).
    line = ''
    if online_only:
        line = (f'<p class="e-text" style="margin:0 0 12px;font-family:{SANS};font-size:17px;'
                f'line-height:1.55;color:{INK_SOFT};">Nothing near you yet. These are online.</p>')
    see_all = _html.escape(see_all_url, quote=True)
    rows = ''.join(cards)
    # PENDING DESIGN: the "See all gatherings" link's weight and spacing.
    return f"""
{title_image(*_GATHERINGS_TITLE)}
{line}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">{rows}
</table>
<p class="e-text" style="margin:4px 0 24px;font-family:{SANS};font-size:15px;line-height:1.5;">
  <a href="{see_all}" style="color:{INDIGO};font-weight:700;text-decoration:underline;">See all gatherings</a>
</p>
"""


def community_weekly_html(new_members: list[dict], total_members: int, spotlight: Optional[dict], cta_url: str, unsubscribe_url: str,
                          *, personal_line: Optional[str] = None, invite_url: Optional[str] = None,
                          cta_label: str = "Open Discover", question_line: Optional[str] = None,
                          gatherings: Optional[list[dict]] = None, gatherings_online_only: bool = False,
                          gatherings_see_all_url: Optional[str] = None,
                          gathering_url: Optional[Callable[[str], str]] = None) -> str:
    """`personal_line`, `invite_url` and `cta_label` are the held personal
    parts (AHAVAH_E2_PERSONAL_ENABLED); `question_line` is this week's quick
    question (AHAVAH_E2_QUESTION_LINE_ENABLED); `gatherings` and the three
    after it are Gatherings near you (AHAVAH_E2_GATHERINGS_ENABLED); left
    out, the email is as it was."""
    gatherings_html = ''
    if gatherings and gatherings_see_all_url:
        gatherings_html = _gatherings_block(gatherings, gatherings_online_only, gatherings_see_all_url,
                                            gathering_url or (lambda slug: gatherings_see_all_url))
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
{gatherings_html}
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
    preheader = "New members, community size, and this week's spotlight."
    if gatherings_html:
        preheader = "New members, gatherings near you and this week's spotlight."  # NEW LINE
    return render(title=SUBJECT, preheader=preheader, body_html=body, footer_html=footer)
