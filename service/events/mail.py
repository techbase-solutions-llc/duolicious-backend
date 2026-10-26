"""Every gathering email (TEC-1845), on the brand shell, through the
durable outbox.

  guests      event_confirm    the confirm link (3.1)
              event_reminder   the day before (3.2, 3.3)
              event_change     a new time, date or place (3.4)
              event_cancelled  the organiser cancelled (3.5)
  organisers  event_digest     once a day, only with new RSVPs (3.6)
              event_manage     the manage link (3.8)
              event_organiser_note  the manage email with a note above
                               the button: approved, or live (plan item 15)

Each is behind its own switch and events_live (service.events.CAMPAIGN_
SWITCHES), read before queueing and again by the drain. Display type is a
title image, never a typed headline; the design's headings that carry a
title or a number become a body line under it (plan item 14).

Recipients: a guest who is a member is queued as the member (scope
notifications); anyone else as their event:{slug} lead, exempt, since the
guest asked for it, with no List-Unsubscribe; their footer offers "Cancel
my place". An organiser is neither, so their rows name organiser_id
(migration 0071). Every queue runs behind a savepoint, so a mail failure
never undoes the caller. Everything an organiser or a guest typed is
escaped.

Lines marked NEW LINE are not in the export; they wait for /copy-pass and
the owner (plan item 12).

The "Join Ahavah" block (TEC-1845, docs/superpowers/plans/2026-10-22-
events-invite-to-join.md) rides in the confirm and reminder emails of a
guest who is not a member, behind events_join_block and the rest-day rule
(service/events/join.py). Without it each email is as it was.
"""
from __future__ import annotations

import html
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from emails.base import INK, MUTED, SANS, button, chip, is_suppressed_send, render, title_image
from service.campaigns import held, outbox
from service.config import API_BASE_URL, EMAIL_DOMAIN, WEB_BASE_URL

CAMPAIGN_CONFIRM = 'event_confirm'
CAMPAIGN_REMINDER = 'event_reminder'
CAMPAIGN_CHANGE = 'event_change'
CAMPAIGN_CANCELLED = 'event_cancelled'
CAMPAIGN_DIGEST = 'event_digest'
CAMPAIGN_MANAGE = 'event_manage'
CAMPAIGN_NOTE = 'event_organiser_note'
CAMPAIGN_JOIN_INVITE = 'event_join_invite'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = f'support@{EMAIL_DOMAIN}'

SAFETY = ('Meet in a public place, tell a friend where you are going and never send money to '
          'someone you met online.')

# stem, alt, natural CSS width (ahavah-web scripts/render-email-titles.mjs).
# Line breaks as drawn: "Tap to / confirm your / place.", "See you /
# tomorrow.", "This / gathering / changed.", "This / gathering / was
# cancelled.", "New RSVPs." and "Manage your / gatherings.".
TITLES: dict[str, tuple[str, str, int]] = {
    'confirm': ('title-event-confirm', 'Tap to confirm your place.', 318),
    'reminder': ('title-event-reminder', 'See you tomorrow.', 251),
    'change': ('title-event-change', 'This gathering changed.', 242),
    'cancelled': ('title-event-cancelled', 'This gathering was cancelled.', 346),
    'digest': ('title-event-digest', 'New RSVPs.', 270),
    'manage': ('title-event-manage', 'Manage your gatherings.', 315),
    # 3.9, "Meet the / community." (handoff 10-events-join.md, NEW LINE),
    # 569 x 158 at 2x.
    'join_invite': ('title-event-join-invite', 'Meet the community.', 285),
    # Round 2, 10.1, "Your / gathering / is live." (handoff 19, departure 1),
    # 484 x 218 at 2x.
    'live': ('title-gathering-live', 'Your gathering is live.', 242),
}

GUEST_WHY = 'You are getting this because you RSVPed to a gathering on Ahavah.'
CONFIRM_WHY = 'If you did not RSVP, ignore this email and nothing will happen.'
DIGEST_WHY = 'We send this once a day, only on days with new RSVPs.'
MANAGE_WHY = 'Only forward this email to people you trust to run your gatherings.'
MANAGE_LINE = ('Use this button to create, change and cancel your gatherings and see who is coming. '
               'No password needed.')
MANAGE_TTL_LINE = 'This link works for 7 days. You can ask for a new one at any time.'
# NEW LINES (plan item 15): the notes above the manage button.
APPROVED_NOTE = 'Ahavah has approved your request to host.'
APPROVED_SUBJECT = 'Your request to host on Ahavah is approved'


def live_note(title: str) -> str:
    return f'{title} is live.'  # NEW LINE


def live_subject(title: str) -> str:
    return f'{title} is live on Ahavah'  # NEW LINE


# Round 2, screen 10 (handoff 19-hosting-and-sharing.md), with the 23 Oct
# copy pass the owner approved in full (ahavah-web
# docs/copy/2026-10-23-design-round-copy-pass.md, rows 27, 28, 35 to 43).
LIVE_LINE = 'People can RSVP from its page now. When they do, we email you once a day with who is new.'
LIVE_WHY = 'You are getting this because you host this gathering on Ahavah.'
SHARE_AGAIN_ASK = 'Want more people to come?'
SHARE_AGAIN = 'Share it again'
# The tag on a link the organiser shares (migration 0081): which share
# brought a view or an RSVP.
HOST_TAG = 'host'


# The join block (handoff 10-events-join.md, frames 3.1 to 3.3): the
# approved line and a text link, below the gathering's own actions.
JOIN_LINE = 'Ahavah is matchmaking for Torah-observant believers who hope to marry.'
JOIN_ACTION = 'Join Ahavah'  # NEW LINE


def join_block(url: str) -> str:
    """Body size, behind a hairline; the link's tap area padded to 44 px as
    drawn. 15 px rather than the frame's 14.5, so the phone type scale
    (emails.base) reads it; nothing at 20 px or more. Between the markers
    of join.mark_block, so the outbox drain can take it out at the send."""
    from service.events.join import mark_block
    return mark_block(
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:22px 0 0;"><tr><td style="border-top:1px solid rgba(15,11,31,0.10);'
        f'padding-top:14px;"><p class="e-text" style="margin:0;font-family:{SANS};font-size:15px;'
        f'line-height:1.55;color:{MUTED};">{JOIN_LINE} '
        f'<a class="e-strong" href="{_e(url)}" target="_blank" style="color:{INK};font-weight:700;'
        f'text-decoration:underline;display:inline-block;padding:12px 0;margin:-12px 0;">'
        f'{JOIN_ACTION}</a></p></td></tr></table>')


# 3.9, the invitation to join (handoff 10-events-join.md). Every line but
# JOIN_LINE and GUEST_WHY is new there.
# Wording approved by the owner after the copy pass on 23 Oct 2026
# (ahavah-web docs/copy/2026-10-23-invite-join-copy-pass.md).
JOIN_INVITE_SUBJECT = 'Meet the community on Ahavah'
JOIN_INVITE_ABOUT = ('Members get to know one another with marriage in mind, and families can '
                     'take part.')
JOIN_INVITE_NEAR = ('You asked to hear about gatherings and members near you, and members see '
                    'both on Ahavah.')
JOIN_INVITE_WHY = (GUEST_WHY + ' You ticked “Tell me about Ahavah events and members near me”. '
                   'We send this once.')  # NEW LINE (the second and third sentences)


def join_invite_line(event: dict) -> str:
    """"You RSVPed to {title}.", in person and online alike. The title escaped, bold."""
    return f"You RSVPed to <b>{_e(event['title'])}</b>."


def confirm_url(token: str) -> str:
    """The web page that confirms by a script call, so a mail scanner
    opening the link confirms nothing."""
    return f'{WEB_BASE_URL}/rsvp/confirm/{token}'


def manage_url(token: str) -> str:
    return f'{WEB_BASE_URL}/host/gatherings?t={token}'


def calendar_url(token: str) -> str:
    return f'{API_BASE_URL}/rsvp/{token}/calendar.ics'


def rsvp_url(token: str) -> str:
    return f'{WEB_BASE_URL}/rsvp/{token}'


def page_url(slug: str) -> str:
    return f'{WEB_BASE_URL}/e/{slug}'


def share_url(slug: str, tag: str = HOST_TAG) -> str:
    """The gathering's page with a share tag (migration 0081)."""
    return f'{page_url(slug)}?s={tag}'


def image_url(slug: str, size: str) -> str:
    """The kit's story ('story') or post ('feed') image (ahavah-web
    src/app/e/[slug]/share-image/route.ts)."""
    return f'{page_url(slug)}/share-image?size={size}'


def guests_url(slug: str, token: str) -> str:
    """The host page with the guest list, opening the share kit."""
    return f'{WEB_BASE_URL}/host/gatherings/{slug}/guests?t={token}&share=1'


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

def _e(text: object) -> str:
    return html.escape('' if text is None else str(text))


def _title(key: str) -> str:
    stem, alt, width = TITLES[key]
    return title_image(f'{stem}.png', f'{stem}-wht.png', alt, width)


def _lead(text: str) -> str:
    """The line under the title that carries a title or a number: body size, bold."""
    return (f'<p class="e-strong" style="margin:0 0 18px;font-family:{SANS};font-size:17px;'
            f'font-weight:700;line-height:1.55;color:{INK};">{text}</p>')


def _link(label: str, href: str) -> str:
    return (f'<p style="margin:0 0 18px;font-family:{SANS};font-size:16px;line-height:1.5;">'
            f'<a href="{_e(href)}" style="color:{INK};font-weight:700;text-decoration:underline;">{label}</a></p>')


def _after_button(text: str, size: int) -> str:
    """A quiet line under a button."""
    return (f'<p class="e-text" style="margin:14px 0 0;font-family:{SANS};font-size:{size}px;'
            f'line-height:1.55;color:{MUTED};">{text}</p>')


def _panel(rows_html: str) -> str:
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">
      <tr><td class="e-callout" bgcolor="#F4F2EC" style="padding:14px 16px;background:#F4F2EC;border-radius:12px;font-family:{SANS};color:{INK};">
        {rows_html}
      </td></tr>
    </table>"""


def _line(text: str, *, bold: bool = False, size: int = 15, bottom: int = 6) -> str:
    weight = 700 if bold else 500
    cls = 'e-strong' if bold else 'e-text'
    return (f'<p class="{cls}" style="margin:0 0 {bottom}px;font-family:{SANS};font-size:{size}px;'
            f'font-weight:{weight};line-height:1.5;color:{INK};">{text}</p>')


def _when(event: dict) -> tuple[str, str]:
    from service.events.fields import when_words
    s, e = event['starts_at'], event['ends_at']
    s = datetime.fromisoformat(s) if isinstance(s, str) else s
    e = datetime.fromisoformat(e) if isinstance(e, str) else e
    return when_words(s, e, event['tz'], event['tz_label'])


def _place_line(event: dict, shown: bool) -> str:
    """Before confirming, the city or "Online"; after, the venue or the
    call link (export 3.1, 3.2)."""
    if event['mode'] == 'online':
        url = event.get('online_url')
        if shown and url:
            return f'<a href="{_e(url)}" style="color:{INK};font-weight:600;">{_e(url)}</a>'
        return 'Online'
    if shown and event.get('venue'):
        return _e(event['venue'])
    return _e(event.get('city'))


def _facts(event: dict, shown: bool) -> str:
    day, time = _when(event)
    return _panel(_line(_e(event['title']), bold=True, bottom=8)
                  + _line(f'{_e(day)}, {_e(time)}')
                  + _line(_place_line(event, shown))
                  + _line(f"Hosted by {_e(event['organiser']['name'])}", bottom=0))


def _safety(event: dict) -> str:
    return held.para(SAFETY, size=15, bottom=0, muted=True) if event['mode'] == 'in_person' else ''


def _footer(reason: str, *, cancel_token: Optional[str] = None) -> str:
    link = f'color:{MUTED};font-weight:600;text-decoration:underline;'
    cancel = (f'<a href="{_e(rsvp_url(cancel_token))}" style="{link}">Cancel my place</a>'
              '&nbsp;&nbsp;&middot;&nbsp;&nbsp;') if cancel_token else ''
    return ('Ahavah &middot; Matchmaking for Torah-observant believers.<br/>'
            f'{reason}'
            f'<div style="margin-top:14px;">{cancel}'
            f'<a href="https://ahavah.app/faq" style="{link}">Help</a></div>')


def _shell(subject: str, preheader: str, body: str, footer: str) -> str:
    return render(title=_e(subject), preheader=preheader, body_html=body, footer_html=footer)


# ---------------------------------------------------------------------------
# The builders. `view` is rsvp.rsvp_view's {event, rsvp}.
# ---------------------------------------------------------------------------

def confirm_email(view: dict, token: str, *, join_url: Optional[str] = None) -> tuple[str, str]:
    """3.1. No safety note: the address is not shared yet. The overline
    repeated the title, so it is dropped (as the checklist invite's was).
    With `join_url`, the join block after the line under the button: the
    button stays the only one."""
    ev = view['event']
    subject = f"Confirm your place at {ev['title']}"  # NEW LINE
    share = ('We share the link once you confirm.' if ev['mode'] == 'online'  # NEW LINE
             else 'We share the address once you confirm.')
    body = (_title('confirm') + _facts(ev, shown=False) + button('Confirm my place', confirm_url(token))
            + _after_button(share, 15) + (join_block(join_url) if join_url else ''))
    return subject, _shell(subject, share, body, _footer(CONFIRM_WHY))


def reminder_email(view: dict, token: str, *, join_url: Optional[str] = None) -> tuple[str, str]:
    """3.2 and 3.3: the venue or the call link, the safety note in person.
    With `join_url`, the join block after "Cancel my place" and the safety
    note, before the footer."""
    ev = view['event']
    subject = f"Tomorrow: {ev['title']}"  # NEW LINE
    day, time = _when(ev)
    body = (chip('Tomorrow') + _title('reminder') + _facts(ev, shown=True)
            + button('Add to calendar', calendar_url(token))
            + '<div style="height:14px;line-height:14px;">&nbsp;</div>'
            + _link('Cancel my place', rsvp_url(token)) + _safety(ev)
            + (join_block(join_url) if join_url else ''))
    return subject, _shell(subject, _e(f'{day}, {time}'), body, _footer(GUEST_WHY, cancel_token=token))


def _body(text: str) -> str:
    """3.9's body lines: 16 px, ink, as drawn."""
    return (f'<p class="e-text" style="margin:0 0 16px;font-family:{SANS};font-size:16px;'
            f'line-height:1.6;color:{INK};">{text}</p>')


def join_invite_email(event: dict, join_url: str, unsubscribe_url: str) -> tuple[str, str]:
    """3.9: the title image, the gathering's title as a body line (no
    organiser, Owner decision 10; no guest name; no venue or call link),
    what Ahavah is, one "Join Ahavah" button and a news footer. It does not
    thank the guest for coming: they may not have gone."""
    subject = JOIN_INVITE_SUBJECT
    body = (_title('join_invite') + _body(join_invite_line(event))
            + _body(f'{JOIN_LINE} {JOIN_INVITE_ABOUT}') + _body(JOIN_INVITE_NEAR)
            + '<div style="height:6px;line-height:6px;">&nbsp;</div>'
            + button(JOIN_ACTION, _e(join_url)))
    return subject, _shell(subject, JOIN_LINE, body, held.footer(JOIN_INVITE_WHY, _e(unsubscribe_url)))


def _start_word(time_words: str) -> str:
    return time_words.split(' to ')[0].split(',')[0]


def change_line(title: str, before: dict, after: dict) -> str:
    """The sentence under the change title (export 3.4 for a new time;
    NEW LINES for a new date, place or mode). Plain text: escape it."""
    if after.get('mode') == 'online' and before.get('mode') != 'online':
        return f'{title} is now online'
    if after.get('date') != before.get('date'):
        return f"{title} is now on {after['date']}"
    place_after = after.get('venue') or after.get('place')
    place_before = before.get('venue') or before.get('place')
    if place_after != place_before and after.get('mode') != 'online':
        return f'{title} is now at {place_after}'
    return f"{title} now starts at {_start_word(after.get('time') or '')}"


def _facts_words(f: dict) -> str:
    place = f.get('venue') or f.get('place')
    return f"{_e(f.get('date'))}, {_e(f.get('time'))}" + (f', {_e(place)}' if place else '')


def change_email(view: dict, token: str, before: dict, after: dict) -> tuple[str, str]:
    """3.4: before and now, the guest's place still saved."""
    ev = view['event']
    subject = f"A change to {ev['title']}"  # NEW LINE
    line = change_line(ev['title'], before, after)
    rows = (_line('Before', size=13, bottom=2) + _line(_facts_words(before), bold=True, bottom=12)
            + _line('Now', size=13, bottom=2) + _line(_facts_words(after), bold=True, bottom=0))
    body = (chip('A change') + _title('change') + _lead(_e(line)) + _panel(rows)
            + held.para('Everything else stays the same. Your place is still saved.')
            + _link('Cancel my place', rsvp_url(token)) + _safety(ev))
    return subject, _shell(subject, _e(line), body, _footer(GUEST_WHY, cancel_token=token))


def cancelled_email(view: dict, token: Optional[str] = None) -> tuple[str, str]:
    """3.5: the organiser's note quoted, signed with their name."""
    ev = view['event']
    line = f"{ev['title']} was cancelled"
    subject = line  # NEW LINE
    note = ''
    if ev.get('cancel_note'):
        note = _panel(_line(f"“{_e(ev['cancel_note'])}”", bottom=6)
                      + _line(_e(ev['organiser']['name']), size=13, bottom=0))
    body = (chip('Cancelled') + _title('cancelled') + _lead(_e(line)) + note
            + _link('See other gatherings', f'{WEB_BASE_URL}/events'))
    return subject, _shell(subject, _e(line), body, _footer(GUEST_WHY))


def _people(n: int) -> str:
    return '1 person' if n == 1 else f'{n} people'


def digest_lead(n: int, title: str) -> str:
    return f'1 new RSVP for {title}' if n == 1 else f'{n} new RSVPs for {title}'  # 1: NEW LINE


def digest_email(event: dict, new_rsvps: list[dict], total_going: int,
                 manage_token: str, *, share: bool = False) -> tuple[str, str]:
    """3.6: names and party sizes, never an email address. With `share`
    (the organiser kit is on for them), round 2's quiet line after the
    list (10.4): a text link to the host page with the kit."""
    line = digest_lead(len(new_rsvps), event['title'])
    subject = line  # NEW LINE
    rows = ''.join(
        f'<tr><td class="e-strong" style="padding:8px 0;font-family:{SANS};font-size:15px;font-weight:700;'
        f'color:{INK};">{_e(r["name"])}</td><td class="e-text" align="right" style="padding:8px 0;'
        f'font-family:{SANS};font-size:13px;color:{MUTED};">{_people(int(r["party_size"]))}</td></tr>'
        for r in new_rsvps)
    table = _panel(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>')
    again = ''
    if share and event.get('slug'):
        again = held.para(
            f'{SHARE_AGAIN_ASK} <a class="e-strong" href="{_e(guests_url(event["slug"], manage_token))}" '
            f'target="_blank" style="color:{INK};font-weight:700;text-decoration:underline;display:inline-block;'
            f'padding:12px 0;margin:-12px 0;">{SHARE_AGAIN}</a>', size=15)
    body = (chip('Today') + _title('digest') + _lead(_e(line)) + table
            + held.para(f'<b>{total_going} going</b> in total.') + again
            + button('Manage your gathering', manage_url(manage_token)))
    return subject, _shell(subject, _e(line), body, _footer(DIGEST_WHY))


def _town(city: Optional[str]) -> str:
    return (city or '').split(',')[0].strip()


def _start(event: dict) -> datetime:
    s = event['starts_at']
    return datetime.fromisoformat(s) if isinstance(s, str) else s


def announcement(event: dict) -> str:
    """The suggested group announcement, in the organiser's voice (copy
    pass rows 27 and 28), as ahavah-web src/lib/events/share-text.ts has
    it: the title, day, start and town, never the venue or the call link.
    Plain text: escape it."""
    import zoneinfo

    from service.events.fields import _clock, _day
    start = _start(event).astimezone(zoneinfo.ZoneInfo(event['tz']))
    day, time = _day(start, year=False), _clock(start)
    host, title, link = event['organiser']['name'], event['title'], share_url(event['slug'])
    if event['mode'] == 'online':
        return (f"Shalom all. {host} is hosting {title} online on {day} at {time} {event['tz_label']}. "
                f'Join from anywhere. RSVP here: {link}')
    return (f'Shalom all. {host} is hosting {title} on {day} at {time} in {_town(event.get("city"))}. '
            f'Everyone is welcome. RSVP here: {link}')


def _text_link(label: str, href: str) -> str:
    """A text link with a 44 px tap area, as 10.1 draws them."""
    return (f'<p style="margin:0 0 4px;font-family:{SANS};font-size:15px;line-height:1.5;">'
            f'<a class="e-strong" href="{_e(href)}" target="_blank" style="color:{INK};font-weight:700;'
            f'text-decoration:underline;display:inline-block;padding:12px 0;margin:-6px 0;">{label}</a></p>')


def live_email(event: dict, token: str) -> tuple[str, str]:
    """Round 2, 10.1 and 10.2, "is live" with the organiser share kit: the
    title image, the line, the gathering's title, day, time and town (or
    Online), "See your gathering", then "Share it": its page with the
    host's tag, the story and post images to download and the
    announcement to copy; "Manage your gathering" last. Nothing at 20 px
    or more but the title image. Never the venue or the call link."""
    title = event['title']
    subject = live_subject(title)
    day, time = _when(event)
    place = 'Online' if event['mode'] == 'online' else _e(event.get('city'))
    facts = _panel(_line(_e(title), bold=True, bottom=8) + _line(f'{_e(day)}, {_e(time)}')
                   + _line(place, bottom=0))
    link = share_url(event['slug'])
    kit = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
           'style="margin:22px 0 0;"><tr><td style="border-top:1px solid rgba(15,11,31,0.10);padding-top:14px;">'
           + _line('Share it', bold=True, size=16, bottom=10)
           + _line(f'Its page: <a class="e-strong" href="{_e(link)}" target="_blank" style="color:{INK};'
                   f'font-weight:700;text-decoration:underline;word-break:break-all;">{_e(link)}</a>',
                   bottom=10)
           + _text_link('Download the story image', image_url(event['slug'], 'story'))
           + _text_link('Download the post image', image_url(event['slug'], 'feed'))
           + f'<p class="e-text" style="margin:14px 0 6px;font-family:{SANS};font-size:12px;font-weight:800;'
             f'letter-spacing:0.12em;text-transform:uppercase;color:{MUTED};">A short announcement for your group</p>'
           + _panel(_line(_e(announcement(event)), bottom=0))
           + '</td></tr></table>')
    body = (_title('live') + held.para(LIVE_LINE, size=15) + facts + button('See your gathering', page_url(event['slug']))
            + kit + _link('Manage your gathering', manage_url(token)))
    return subject, _shell(subject, _e(LIVE_LINE), body, _footer(LIVE_WHY))


def manage_email(token: str, note: Optional[str] = None, *,
                 subject: Optional[str] = None) -> tuple[str, str]:
    """3.8, and the organiser notes: one line above the button. The
    overline repeated the title, so it is dropped."""
    subject = subject or 'Manage your gatherings on Ahavah'  # NEW LINE
    body = (_title('manage') + (_lead(_e(note)) if note else '') + held.para(MANAGE_LINE)
            + button('Manage your gatherings', manage_url(token))
            + _after_button(MANAGE_TTL_LINE, 13))
    return subject, _shell(subject, _e(note or MANAGE_LINE), body, _footer(MANAGE_WHY))


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

def _on(campaign: str) -> bool:
    from service.events import CAMPAIGN_SWITCHES, switch_on
    return switch_on(CAMPAIGN_SWITCHES[campaign])


def _guarded(tx, name: str, fn: Callable[[], Optional[int]]) -> Optional[int]:
    tx.execute(f'SAVEPOINT {name}')
    try:
        out = fn()
    except Exception:
        tx.execute(f'ROLLBACK TO SAVEPOINT {name}')
        print(traceback.format_exc())
        return None
    tx.execute(f'RELEASE SAVEPOINT {name}')
    return out


def _guest_to(tx, r: dict) -> Optional[dict]:
    """The member or the lead an RSVP mails, or None (suppressed or neither)."""
    if r['person_id'] is not None:
        row = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=r['person_id'])).fetchone()
        to = dict(person_id=r['person_id'], email=row['email']) if row else None
    elif r['lead_id'] is not None:
        to = dict(lead_id=r['lead_id'], email=r['email'])
    else:
        to = None
    if to is None or is_suppressed_send(to['email']):
        return None
    return to


def _queue_guest(tx, *, campaign: str, campaign_id: str, to: dict, subject: str, html_: str) -> Optional[int]:
    if 'person_id' in to:
        from service.unsubscribe import make_url
        unsub = make_url(UNSUB_SCOPE, to['email'], WEB_BASE_URL)
        return held.queue(tx, campaign=campaign, campaign_id=campaign_id, person_id=to['person_id'],
                          email=to['email'], subject=subject, html=html_, from_addr=FROM_ADDR,
                          unsub_scope=UNSUB_SCOPE, unsub_url=unsub)
    return outbox.enqueue_for_lead(tx, campaign=campaign, campaign_id=campaign_id, lead_id=to['lead_id'],
                                   email=to['email'], subject=subject, html=html_, from_addr=FROM_ADDR,
                                   list_unsubscribe=None, marketing=False)


def _queue_organiser(tx, *, campaign: str, campaign_id: str, organiser_id: int, subject: str,
                     html_: str) -> Optional[int]:
    row = tx.execute('SELECT email FROM organiser WHERE id = %(i)s AND revoked_at IS NULL',
                     dict(i=organiser_id)).fetchone()
    if row is None or is_suppressed_send(row['email']):
        return None
    return outbox.enqueue_for_organiser(tx, campaign=campaign, campaign_id=campaign_id,
                                        organiser_id=organiser_id, email=row['email'],
                                        subject=subject, html=html_, from_addr=FROM_ADDR)


def _already(tx, campaign: str, campaign_id: str) -> bool:
    return tx.execute('SELECT 1 FROM email_outbox WHERE campaign = %(c)s AND campaign_id = %(i)s LIMIT 1',
                      dict(c=campaign, i=campaign_id)).fetchone() is not None


def _rsvp_row(tx, rsvp_id: int) -> Optional[dict]:
    row = tx.execute('SELECT * FROM event_rsvp WHERE id = %(i)s AND erased_at IS NULL',
                     dict(i=rsvp_id)).fetchone()
    return dict(row) if row else None


def _join_url_for(tx, r: dict, now: Optional[datetime] = None) -> Optional[str]:
    """The join link for this RSVP's email, or None: a guest who is not a
    member (join.offers_join), outside a rest period and inside the known
    calendar (join.mail_block_allowed)."""
    from service.events import join
    now = now or datetime.now(timezone.utc)
    if not join.offers_join(tx, r) or not join.mail_block_allowed(now):
        return None
    row = tx.execute('SELECT slug FROM event WHERE id = %(i)s', dict(i=r['event_id'])).fetchone()
    return join.join_url(row['slug']) if row else None


def queue_confirm(tx, rsvp_id: int, token: str) -> Optional[int]:
    """The confirm link, once per send (the first and each "Send it again")."""
    from service.events.rsvp import rsvp_view
    if not _on(CAMPAIGN_CONFIRM):
        return None

    def go():
        r = _rsvp_row(tx, rsvp_id)
        to = _guest_to(tx, r) if r else None
        if to is None:
            return None
        subject, body = confirm_email(rsvp_view(tx, token), token, join_url=_join_url_for(tx, r))
        return _queue_guest(tx, campaign=CAMPAIGN_CONFIRM, campaign_id=f"{rsvp_id}:{r['resends']}",
                            to=to, subject=subject, html_=body)
    return _guarded(tx, 'event_confirm', go)


def _confirmed_guests(tx, event_id: int) -> list[dict]:
    return [dict(r) for r in tx.execute(
        """SELECT * FROM event_rsvp WHERE event_id = %(e)s AND status = 'going'
              AND confirmed_at IS NOT NULL AND erased_at IS NULL ORDER BY id""",
        dict(e=event_id)).fetchall()]


def _for_each_guest(tx, event_id: int, campaign: str, campaign_id_for: Callable[[dict], str],
                    build: Callable[[dict, str], tuple[str, str]], *, new_token: bool) -> int:
    """One email per confirmed guest. A guest gets a fresh token only when
    their email is about to be queued, so a link retires only when a newer
    one is on its way."""
    from service.events import rsvp as rsvp_mod
    n = 0
    for r in _confirmed_guests(tx, event_id):
        cid = campaign_id_for(r)
        to = _guest_to(tx, r)
        if to is None or _already(tx, campaign, cid):
            continue

        def go(r=r, cid=cid, to=to):
            token = rsvp_mod.reissue_token(tx, r['id']) if new_token else None
            subject, body = build(r, token)
            return _queue_guest(tx, campaign=campaign, campaign_id=cid, to=to, subject=subject, html_=body)
        if _guarded(tx, f'{campaign}_{r["id"]}', go) is not None:
            n += 1
    return n


def queue_change(tx, event_id: int) -> int:
    """Each confirmed guest hears once about each change (campaign id by
    changed_at), with a fresh link."""
    from service.events.rsvp import rsvp_view
    if not _on(CAMPAIGN_CHANGE):
        return 0
    ev = tx.execute('SELECT changed_at, change_before, change_after FROM event WHERE id = %(i)s',
                    dict(i=event_id)).fetchone()
    if ev is None or ev['changed_at'] is None:
        return 0
    stamp = ev['changed_at'].astimezone(timezone.utc).strftime('%Y%m%d%H%M%S')
    return _for_each_guest(
        tx, event_id, CAMPAIGN_CHANGE, lambda r: f"{r['id']}:{stamp}",
        lambda r, token: change_email(rsvp_view(tx, token), token, ev['change_before'], ev['change_after']),
        new_token=True)


def queue_cancelled(tx, event_id: int) -> int:
    """Each confirmed guest hears the gathering was cancelled. The email
    holds no link of the guest's own, so no token is reissued."""
    from service.events import public
    if not _on(CAMPAIGN_CANCELLED):
        return 0
    row = tx.execute('SELECT slug FROM event WHERE id = %(i)s', dict(i=event_id)).fetchone()
    if row is None:
        return 0
    view = dict(event=public.view_of(public.event_row(tx, row['slug']), datetime.now(timezone.utc)))
    return _for_each_guest(tx, event_id, CAMPAIGN_CANCELLED, lambda r: str(r['id']),
                           lambda r, token: cancelled_email(view), new_token=False)


def reminder_campaign_id(rsvp_id: int, starts_at: datetime) -> str:
    return f"{rsvp_id}:{starts_at.astimezone(timezone.utc):%Y%m%d%H%M}"


def queue_reminder(tx, rsvp_id: int, token: str) -> Optional[int]:
    """The day before. The caller issues the token (rsvp.reissue_token) and
    checks reminder_already first, so a repeat tick retires no link."""
    from service.events.rsvp import rsvp_view
    if not _on(CAMPAIGN_REMINDER):
        return None

    def go():
        r = _rsvp_row(tx, rsvp_id)
        if r is None or r['status'] != 'going' or r['confirmed_at'] is None:
            return None
        to = _guest_to(tx, r)
        if to is None:
            return None
        starts = tx.execute('SELECT starts_at FROM event WHERE id = %(i)s', dict(i=r['event_id'])).fetchone()
        subject, body = reminder_email(rsvp_view(tx, token), token, join_url=_join_url_for(tx, r))
        return _queue_guest(tx, campaign=CAMPAIGN_REMINDER,
                            campaign_id=reminder_campaign_id(rsvp_id, starts['starts_at']),
                            to=to, subject=subject, html_=body)
    return _guarded(tx, 'event_reminder', go)


def queue_join_invite(tx, rsvp: dict, event: dict, now: datetime) -> Optional[int]:
    """The one invitation to join, as news to the RSVP's event:{slug} lead.
    None unless, in this order: the switch; the ticked box; a visitor's
    lead (no person_id); an address no member holds now; not suppressed;
    news_refusal passes (confirmed, consent, not unsubscribed) and no lead
    row of the address has left the news. Then the
    once-per-address record (lead_join_invite, 0076) is written in the same
    savepoint as the queue: no record row means the address had its
    invitation, and a queue that refuses takes the record back with it.
    The caller (jobs.queue_join_invites) decides when it is due."""
    from service.events import join
    from service.leads import address_unsubscribed, news_refusal
    from service.unsubscribe import make_url
    if not _on(CAMPAIGN_JOIN_INVITE) or not rsvp.get('marketing_consent'):
        return None
    if rsvp.get('lead_id') is None or rsvp.get('person_id') is not None or not rsvp.get('email'):
        return None
    if join.is_member_address(tx, rsvp['normalized_email']) or is_suppressed_send(rsvp['email']):
        return None
    # The lead row alone is not enough: another gathering's row may carry
    # the address's unsubscribe while this fresh one does not.
    if news_refusal(tx, rsvp['lead_id']) is not None or address_unsubscribed(tx, rsvp['normalized_email']):
        return None
    tx.execute('SAVEPOINT event_join_invite')
    try:
        claimed = tx.execute(
            """INSERT INTO lead_join_invite (normalized_email, event_id) VALUES (%(ne)s, %(e)s)
               ON CONFLICT DO NOTHING RETURNING normalized_email""",
            dict(ne=rsvp['normalized_email'], e=event['id'])).fetchone()
        out = None
        if claimed is not None:
            unsub = make_url('news', rsvp['email'], WEB_BASE_URL)
            subject, body = join_invite_email(event, join.join_url(event['slug']), unsub)
            out = outbox.enqueue_for_lead(
                tx, campaign=CAMPAIGN_JOIN_INVITE, campaign_id=str(event['id']), lead_id=rsvp['lead_id'],
                email=rsvp['email'], subject=subject, html=body, from_addr=FROM_ADDR,
                list_unsubscribe=held.list_unsubscribe(unsub), marketing=True)
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT event_join_invite')
        print(traceback.format_exc())
        return None
    if out is None:
        tx.execute('ROLLBACK TO SAVEPOINT event_join_invite')
        return None
    tx.execute('RELEASE SAVEPOINT event_join_invite')
    return out


def reminder_already(tx, rsvp_id: int, starts_at: datetime) -> bool:
    return _already(tx, CAMPAIGN_REMINDER, reminder_campaign_id(rsvp_id, starts_at))


def queue_digest(tx, event_id: int, day: date) -> Optional[int]:
    """The organiser's digest of RSVPs confirmed since the last one, with a
    fresh manage link. The RSVPs it names are marked digested in the same
    transaction. None when there is nothing new."""
    from service.events.organisers import issue_link, kit_on
    if not _on(CAMPAIGN_DIGEST):
        return None
    cid = f'{event_id}:{day.isoformat()}'
    if _already(tx, CAMPAIGN_DIGEST, cid):
        return None

    def go():
        ev = dict(tx.execute('SELECT id, slug, title, organiser_id FROM event WHERE id = %(i)s',
                             dict(i=event_id)).fetchone())
        new = [dict(r) for r in tx.execute(
            """SELECT id, name, party_size FROM event_rsvp
                WHERE event_id = %(e)s AND status = 'going' AND confirmed_at IS NOT NULL
                  AND digested_at IS NULL AND erased_at IS NULL ORDER BY confirmed_at, id""",
            dict(e=event_id)).fetchall()]
        if not new:
            return None
        total = tx.execute(
            """SELECT COALESCE(SUM(party_size), 0)::int AS n FROM event_rsvp
                WHERE event_id = %(e)s AND status = 'going' AND confirmed_at IS NOT NULL""",
            dict(e=event_id)).fetchone()['n']
        o = tx.execute('SELECT email, member_person_id FROM organiser WHERE id = %(i)s',
                       dict(i=ev['organiser_id'])).fetchone()
        subject, body = digest_email(ev, new, total, issue_link(tx, ev['organiser_id']),
                                     share=o is not None and kit_on(dict(o)))
        out = _queue_organiser(tx, campaign=CAMPAIGN_DIGEST, campaign_id=cid,
                               organiser_id=ev['organiser_id'], subject=subject, html_=body)
        if out is not None:
            tx.execute('UPDATE event_rsvp SET digested_at = NOW() WHERE id = ANY(%(i)s)',
                       dict(i=[r['id'] for r in new]))
        return out
    return _guarded(tx, 'event_digest', go)


def queue_live(tx, event_id: int) -> Optional[int]:
    """The organiser is told their gathering is live, with a fresh manage
    link: round 2's email with the share kit while the kit is on for them
    (hosting and app_entries, organisers.kit_on), else the manage email
    with the live note, as before. One switch for both, event_organiser_note."""
    from service.events.organisers import issue_link, kit_on
    from service.leads import token_hash
    row = tx.execute(
        """SELECT e.id, e.slug, e.title, e.starts_at, e.ends_at, e.tz, e.tz_label, e.mode, e.city,
                  e.country, e.organiser_id, o.name AS organiser_name, o.email AS organiser_email,
                  o.member_person_id
             FROM event e JOIN organiser o ON o.id = e.organiser_id WHERE e.id = %(i)s""",
        dict(i=event_id)).fetchone()
    if row is None:
        return None
    oid = row['organiser_id']
    if not kit_on(dict(email=row['organiser_email'], member_person_id=row['member_person_id'])):
        return queue_manage_link(tx, oid, issue_link(tx, oid), note=live_note(row['title']),
                                 subject=live_subject(row['title']))
    if not _on(CAMPAIGN_NOTE):
        return None
    token = issue_link(tx, oid)
    event = dict(row, organiser=dict(name=row['organiser_name']))

    def go():
        s, body = live_email(event, token)
        return _queue_organiser(tx, campaign=CAMPAIGN_NOTE, campaign_id=f'{oid}:{token_hash(token)[:12]}',
                                organiser_id=oid, subject=s, html_=body)
    return _guarded(tx, 'event_live', go)


def queue_manage_link(tx, organiser_id: int, token: str, *, note: Optional[str] = None,
                      subject: Optional[str] = None) -> Optional[int]:
    """The manage link, alone (event_manage) or under a note (the approved
    or live note, event_organiser_note)."""
    from service.leads import token_hash
    campaign = CAMPAIGN_NOTE if note else CAMPAIGN_MANAGE
    if not _on(campaign):
        return None

    def go():
        s, body = manage_email(token, note, subject=subject)
        return _queue_organiser(tx, campaign=campaign, campaign_id=f'{organiser_id}:{token_hash(token)[:12]}',
                                organiser_id=organiser_id, subject=s, html_=body)
    return _guarded(tx, 'event_manage', go)


# ---------------------------------------------------------------------------
# Proof previews (scripts/send_event_proofs.py): sample data only.
# ---------------------------------------------------------------------------

_SAMPLE_START = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
_SAMPLE_TOKEN = 'proof-token-proof-token-proof-tok'


def sample_event(**over) -> dict:
    ev = dict(slug='marriage-preparation-evening-a1b2c3', title='Marriage preparation evening',
              starts_at=_SAMPLE_START.isoformat(), ends_at=(_SAMPLE_START + timedelta(hours=3)).isoformat(),
              tz='America/Chicago', tz_label='Central Time', mode='in_person', city='Dallas',
              country='United States', venue='Grace Fellowship hall, 14 Elm Street, Dallas',
              organiser=dict(name='Grace Fellowship', kind='fellowship_leader'), cancel_note=None)
    ev.update(over)
    return ev


def sample_online_event(**over) -> dict:
    start = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)
    return sample_event(**{**dict(
        slug='preparing-for-marriage-a-talk-d4e5f6', title='Preparing for marriage: a talk and questions',
        starts_at=start.isoformat(), ends_at=(start + timedelta(minutes=75)).isoformat(),
        tz='Europe/London', tz_label='UK time', mode='online', city=None, country=None, venue=None,
        online_url='https://meet.example.com/ahavah-talk', organiser=dict(name='Ahavah', kind='ahavah')),
        **over})


def sample_view(*, title: Optional[str] = None, organiser: Optional[str] = None, note: Optional[str] = None,
                online: bool = False, confirmed: bool = False) -> dict:
    ev = sample_online_event() if online else sample_event()
    if title is not None:
        ev['title'] = title
    if organiser is not None:
        ev['organiser'] = dict(name=organiser, kind='other')
    if note is not None:
        ev['cancel_note'] = note
    if not confirmed:
        ev = {k: v for k, v in ev.items() if k not in ('venue', 'online_url')}
    return dict(event=ev, rsvp=dict(name='Hannah Okafor', party_size=2, status='going', confirmed=confirmed))


_SAMPLE_BEFORE = dict(date='Saturday 7 November 2026', time='5pm to 9pm, Central Time', place='Dallas',
                      venue='Grace Fellowship hall, 14 Elm Street, Dallas', mode='in_person')
_SAMPLE_AFTER = dict(_SAMPLE_BEFORE, time='6pm to 9pm, Central Time')


def preview_confirm(to: str) -> tuple[str, str]:
    return confirm_email(sample_view(), _SAMPLE_TOKEN)


def preview_confirm_online(to: str) -> tuple[str, str]:
    return confirm_email(sample_view(online=True), _SAMPLE_TOKEN)


def preview_reminder(to: str) -> tuple[str, str]:
    return reminder_email(sample_view(confirmed=True), _SAMPLE_TOKEN)


def preview_reminder_online(to: str) -> tuple[str, str]:
    return reminder_email(sample_view(online=True, confirmed=True), _SAMPLE_TOKEN)


def _sample_join_url(online: bool = False) -> str:
    from service.events.join import join_url
    return join_url((sample_online_event() if online else sample_event())['slug'])


def preview_confirm_join(to: str) -> tuple[str, str]:
    return confirm_email(sample_view(), _SAMPLE_TOKEN, join_url=_sample_join_url())


def preview_confirm_online_join(to: str) -> tuple[str, str]:
    return confirm_email(sample_view(online=True), _SAMPLE_TOKEN, join_url=_sample_join_url(True))


def preview_reminder_join(to: str) -> tuple[str, str]:
    return reminder_email(sample_view(confirmed=True), _SAMPLE_TOKEN, join_url=_sample_join_url())


def preview_reminder_online_join(to: str) -> tuple[str, str]:
    return reminder_email(sample_view(online=True, confirmed=True), _SAMPLE_TOKEN,
                          join_url=_sample_join_url(True))


def _preview_join_invite(to: str, ev: dict) -> tuple[str, str]:
    from service.events.join import join_url
    from service.unsubscribe import make_url
    return join_invite_email(ev, join_url(ev['slug']), make_url('news', to, WEB_BASE_URL))


def preview_join_invite(to: str) -> tuple[str, str]:
    return _preview_join_invite(to, sample_event())


def preview_join_invite_online(to: str) -> tuple[str, str]:
    return _preview_join_invite(to, sample_online_event())


def preview_change(to: str) -> tuple[str, str]:
    return change_email(sample_view(confirmed=True), _SAMPLE_TOKEN, _SAMPLE_BEFORE, _SAMPLE_AFTER)


def preview_cancelled(to: str) -> tuple[str, str]:
    return cancelled_email(sample_view(
        note='We are sorry. The hall is closed for repairs, and we will share a new date soon.'))


def preview_digest(to: str) -> tuple[str, str]:
    return digest_email(sample_event(), [dict(name='Hannah Okafor', party_size=2),
                                         dict(name='The Adeyemi family', party_size=4),
                                         dict(name='Lydia Cruz', party_size=1)], 14, _SAMPLE_TOKEN)


def preview_manage(to: str) -> tuple[str, str]:
    return manage_email(_SAMPLE_TOKEN)


def preview_approved(to: str) -> tuple[str, str]:
    return manage_email(_SAMPLE_TOKEN, APPROVED_NOTE, subject=APPROVED_SUBJECT)


def preview_live(to: str) -> tuple[str, str]:
    """The live note alone: the email while the share kit is off."""
    title = 'Marriage preparation evening'
    return manage_email(_SAMPLE_TOKEN, live_note(title), subject=live_subject(title))


def preview_live_kit(to: str) -> tuple[str, str]:
    return live_email(sample_event(), _SAMPLE_TOKEN)


def preview_live_kit_online(to: str) -> tuple[str, str]:
    return live_email(sample_online_event(), _SAMPLE_TOKEN)


def preview_digest_share(to: str) -> tuple[str, str]:
    return digest_email(sample_event(), [dict(name='Hannah Okafor', party_size=2),
                                         dict(name='The Adeyemi family', party_size=4),
                                         dict(name='Lydia Cruz', party_size=1)], 14, _SAMPLE_TOKEN,
                        share=True)
