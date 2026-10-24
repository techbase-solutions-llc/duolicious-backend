"""The markers around the gatherings parts of member emails (TEC-1845):
Gatherings near you in E2 and the welcome's mention.

Each part is built behind its switch (service.events.member_email_on), but
a row queued in email_outbox keeps the HTML it was built with. The parts
carry these markers so the drain can take them out when, at the send, the
switch is off or the events list is closed (service/campaigns/outbox.py
_send_html), as the events emails' join block does. The rest of the email
still goes."""
from __future__ import annotations

import re
from typing import Literal

START = '<!--ahavah-gatherings-->'
END = '<!--/ahavah-gatherings-->'
_PART = re.compile(re.escape(START) + '.*?' + re.escape(END), re.S)

# The member_email_on switch of each campaign that may carry a part.
SWITCHES: dict[str, Literal['e2_gatherings', 'welcome_gatherings']] = {'e2': 'e2_gatherings', 'welcome': 'welcome_gatherings'}

# E2's preheader names the section only while it is there.
E2_PREHEADER = "New members, community size, and this week's spotlight."
E2_PREHEADER_WITH = "New members, gatherings near you and this week's spotlight."  # NEW LINE


def mark(part_html: str) -> str:
    return START + part_html + END if part_html else ''


def has_part(html: str) -> bool:
    return START in (html or '')


def strip(html: str) -> str:
    """The email without its gatherings part, and with E2's own preheader."""
    return _PART.sub('', html).replace(E2_PREHEADER_WITH, E2_PREHEADER)
