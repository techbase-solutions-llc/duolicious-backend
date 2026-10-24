"""E2 weekly community email (spec 3.5). Replaces emails/digest.py.
Copy rules: NO em dashes. Sentence case."""
from __future__ import annotations

import html as _html
from typing import Callable, Optional
from service.config import EMAIL_DOMAIN
from service.spotlight.country import display_country
from emails.base import render, button, chip, title_image, callout, INK, INK_SOFT, INDIGO, LIME, MUTED, SANS
from emails import gatherings_section

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


# The subhead of Ahavah Gatherings in Member Emails.html (W.1), "Gatherings
# / near you.", at its natural CSS width (handoff 20, titles.json).
_GATHERINGS_TITLE = ("subhead-gatherings-near.png", "subhead-gatherings-near-wht.png", "Gatherings near you.", 181)

# The card's hairline (the kit's --hair, light). In dark clients e-hair
# lightens it, e-tile and e-tile-wd draw the tile as W.1 dark, and the
# e-text, e-strong and e-muted classes keep the card's text readable.
_HAIR = "rgba(15,11,31,0.08)"
# The date tile's tint, the kit's --acc-soft as the email chip draws it.
_ACC_SOFT = "#EDE8FE"
# Text a host typed may hold a long unbroken word (a web address, a joined
# name). It breaks inside the card rather than widen the email past a phone.
_WRAP = "word-break:break-word;overflow-wrap:anywhere;"


def _gathering_card(g: dict, href: str, *, last: bool = False) -> str:
    """One gathering as a table row (W.1): a hairline card with the date
    tile (weekday, day at 18 px and month, stacked in 56 px), the title, the
    city and country or "Online", the organiser and "Ahavah will be there".
    W.1 draws the card as one link: the tile is one, and the whole text
    cell is another, both to the gathering's page. Every organiser field is
    escaped. Raises on a card with no date (a zone the server does not
    know) or a missing field; the caller drops that card. The design's
    small icons (pin, video, spark) are left out: an email cannot carry
    them safely."""
    day_name, day, month = g['date']
    if g['mode'] == 'online':
        place = 'Online'
    else:
        place = ', '.join(_esc(v) for v in (g.get('city'), g.get('country')) if v)
    link = _html.escape(href, quote=True)
    chip_html = ''
    if g.get('ahavah_attending'):
        # No fixed height: a chip that wraps on a narrow phone grows with
        # its text, so no word falls outside the pill.
        chip_html = (f'<span style="display:block;margin-top:6px;"><span style="display:inline-block;padding:5px 10px;'
                     f'line-height:16px;border-radius:999px;background:{LIME};color:{INK};font-family:{SANS};'
                     f'font-size:12px;font-weight:800;">Ahavah will be there</span></span>')
    gap = '4px' if last else '12px'
    return f"""
<tr><td style="padding:0 0 {gap};">
  <table class="e-hair" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;border:1px solid {_HAIR};border-radius:16px;">
    <tr>
      <td width="56" valign="top" style="width:56px;padding:14px 0 14px 16px;">
        <a class="e-tile" href="{link}" style="display:block;width:56px;text-decoration:none;text-align:center;border-radius:14px;background:{_ACC_SOFT};padding:8px 0;font-family:{SANS};">
          <span class="e-tile-wd" style="display:block;font-size:11px;line-height:1.3;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:{INDIGO};">{_esc(str(day_name).upper())}</span>
          <span class="e-strong" style="display:block;font-size:18px;line-height:1.1;font-weight:700;color:{INK};">{_esc(day)}</span>
          <span class="e-muted" style="display:block;font-size:12px;line-height:1.4;color:{MUTED};">{_esc(month)}</span>
        </a>
      </td>
      <td valign="top" style="padding:0;{_WRAP}">
        <a href="{link}" style="display:block;padding:14px 16px 14px 14px;text-decoration:none;font-family:{SANS};{_WRAP}">
          <span class="e-strong" style="display:block;color:{INK};font-size:15px;line-height:1.3;font-weight:700;">{_esc(g['title'])}</span>
          <span class="e-text" style="display:block;font-size:13px;line-height:1.4;color:{MUTED};margin-top:4px;">{place}</span>
          <span class="e-text" style="display:block;font-size:13px;line-height:1.4;color:{INK_SOFT};font-weight:700;margin-top:4px;">{_esc(g['organiser']['name'])}</span>
          {chip_html}
        </a>
      </td>
    </tr>
  </table>
</td></tr>"""


def renderable(gatherings: Optional[list[dict]]) -> list[dict]:
    """The gatherings whose card can be drawn; a card that raises is
    dropped with a warning, as _safe_spotlight_block does, and never the
    email. The sender keeps only these before it mints any link, so a
    section that would not render leaves no link behind."""
    kept = []
    for g in gatherings or []:
        try:
            _gathering_card(g, '')
            kept.append(g)
        except Exception as e:  # one card, never the send
            print(f"community_weekly: dropping gathering {g.get('slug')!r} ({e!r})")
    return kept


def _gatherings_block(gatherings: list[dict], online_only: bool, see_all_url: str,
                      card_url: Callable[[str], str]) -> str:
    """Gatherings near you (TEC-1845; W.1 to W.4 of Ahavah Gatherings in
    Member Emails.html), held behind AHAVAH_E2_GATHERINGS_ENABLED. Left out
    when the member has none (W.4). Built once per recipient inside
    run_campaign's loop, so a card that raises is dropped, never the email.
    Wrapped in gatherings_section's markers, so the drain can take it out
    of a row already queued once the switch is off."""
    # A card is tried before its link is minted, so a dropped card leaves no
    # link behind; the last card kept is drawn with the tighter gap above
    # "See all gatherings".
    kept = renderable(gatherings)
    if not kept:
        return ''
    cards = []
    for i, g in enumerate(kept):
        try:
            cards.append(_gathering_card(g, card_url(g['slug']), last=i == len(kept) - 1))
        except Exception as e:  # one card, never the send
            print(f"community_weekly: dropping gathering {g.get('slug')!r} ({e!r})")
    if not cards:
        return ''
    # W.3, copy 1.5 of the marketing pages: for a member with a region that
    # has no in-person gathering at all (owner decision 5). At the body's
    # 17 px, so a phone shows it at the body's 12 px.
    line = ''
    if online_only:
        line = (f'<p class="e-strong" style="margin:0 0 12px;font-family:{SANS};font-size:17px;'
                f'line-height:1.55;color:{INK};">Nothing near you yet. These are online.</p>')
    see_all = _html.escape(see_all_url, quote=True)
    rows = ''.join(cards)
    # "See all gatherings": a text link padded to a 44 px tap area (W.1).
    return gatherings_section.mark(f"""
<div style="height:6px;line-height:6px;">&nbsp;</div>
{title_image(*_GATHERINGS_TITLE)}
{line}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">{rows}
</table>
<p style="margin:0 0 12px;font-family:{SANS};">
  <a class="e-link" href="{see_all}" style="display:inline-block;padding:12px 0;font-size:15px;line-height:20px;color:{INDIGO};font-weight:700;text-decoration:underline;">See all gatherings</a>
</p>
""")


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
{button(cta_label, cta_url)}

{_invite_block(invite_url)}

<div style="height:20px;line-height:20px;">&nbsp;</div>

{callout("Want to be featured? Turn on Spotlight under Settings, Privacy.")}
{gatherings_html}"""
    footer = f"""
Ahavah &middot; Matchmaking for Torah-observant believers.<br/>
You're receiving the weekly community email as a member of Ahavah.
<div style="margin-top:14px;">
  <a href="{unsubscribe_url}" style="color:{MUTED};font-weight:600;text-decoration:underline;">Stop the weekly email</a>
  &nbsp;&nbsp;&middot;&nbsp;&nbsp;
  <a href="https://ahavah.app/faq" style="color:{MUTED};font-weight:600;text-decoration:underline;">Help</a>
</div>
"""
    # The section comes after the weekly content, as handoff 20 and W.1
    # place it, and E2's preheader names it only while it is there.
    preheader = gatherings_section.E2_PREHEADER_WITH if gatherings_html else gatherings_section.E2_PREHEADER
    return render(title=SUBJECT, preheader=preheader, body_html=body, footer_html=footer)
