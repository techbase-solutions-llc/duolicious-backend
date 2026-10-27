"""The "Your Ahavah" line in the footer of the role emails (TEC-1845;
ahavah-web Claude Design "Ahavah Release 4 Your Ahavah.html", frames 1.6
to 1.9, p25-r4.js mailFoot; copy handoff/copy/24-release-4.md, 1.6 to 1.9).

    Everything held under this email is in Your Ahavah, where you can also
    delete it.

The same line in each role email, under the footer's own reason line,
which stays as it is: organisers (service/events/mail.py, every organiser
email), gathering guests (the confirm, reminder, change and cancelled
emails) and mentors (service/matchmaker/mail.py, the invitation). The
recommender gets no email of their own, so there is nowhere to put the
fourth frame's line.

Behind its own switch, your_ahavah_email_line, which counts only while
the light sign-in is open (service.your_ahavah.on: light_sign_in and
matchmaker_live), since /your-ahavah is not found otherwise. Never to an
address a member holds: that address has a profile, and Your Ahavah
offers it no delete (for_address).

A queued email keeps the HTML it was built with, so the line carries
markers, and the outbox drain takes it out when, at the send, the switch
is off or the address has joined since (service/campaigns/outbox.py
_send_html), as the join block and the gatherings section are.
"""
from __future__ import annotations

import re

from emails.base import MUTED

START = '<!--ahavah-your-ahavah-->'
END = '<!--/ahavah-your-ahavah-->'
_LINE = re.compile(re.escape(START) + '.*?' + re.escape(END), re.S)

LINK_TEXT = 'Your Ahavah'
BEFORE = 'Everything held under this email is in '
AFTER = ', where you can also delete it.'


def url() -> str:
    from service.config import WEB_BASE_URL
    return f'{WEB_BASE_URL}/your-ahavah'


def on() -> bool:
    """The switch, and the light sign-in it links to."""
    from service.campaigns.switches import enabled
    from service.your_ahavah import on as light_sign_in_on
    return enabled('your_ahavah_email_line') and light_sign_in_on()


def block() -> str:
    """The line in the footer's type (13 px, muted, centred), the link bold
    with its tap area padded to 44 px as drawn, between the markers."""
    link = (f'<a href="{url()}" target="_blank" style="color:{MUTED};font-weight:700;'
            'text-decoration:underline;display:inline-block;padding:12px 0;margin:-12px 0;">'
            f'{LINK_TEXT}</a>')
    return f'{START}<div style="margin-top:10px;">{BEFORE}{link}{AFTER}</div>{END}'


def has_line(html: str) -> bool:
    return START in (html or '')


def strip(html: str) -> str:
    return _LINE.sub('', html)


def is_member_address(tx, email: str) -> bool:
    from service.leads import clean_email
    cleaned = clean_email(email)
    if cleaned is None:
        return False
    return tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                      dict(ne=cleaned[1])).fetchone() is not None


def for_address(tx, email: str) -> bool:
    """Whether an email to this address carries the line now."""
    return on() and bool(email) and not is_member_address(tx, email)


def at_send(tx, email: str, html: str) -> str:
    """The HTML to send: without the line once it would not be added now."""
    if has_line(html) and not for_address(tx, email):
        return strip(html)
    return html
