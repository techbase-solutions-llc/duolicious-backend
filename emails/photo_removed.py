"""The note a member gets when one of their photos is taken down (TEC-946).

Built on emails/member_note.py, so it is on the canonical shell with the
"A note from Ahavah." title image. It says three things and nothing else:
what happened, what a profile photo needs, and that they are welcome to add
another. It never says fake and never accuses anyone of anything: a model or
an operator judged a picture, not a person.
"""
from __future__ import annotations

import html as _html

from emails.member_note import send_member_note
from service.config import WEB_BASE_URL

SUBJECT = "About one of your photos"


def send_photo_removed(to_addr: str, name: str | None = None) -> bool:
    """Returns False when the address is suppressed and nothing was sent."""
    first = _html.escape((name or '').strip().split(' ')[0])
    greeting = f"Hi {first}," if first else "Hello,"
    return bool(send_member_note(
        to_addr=to_addr,
        subject=SUBJECT,
        preheader="We have taken one photo down from your profile.",
        paragraphs=[
            greeting,
            "We have taken one of the photos on your profile down.",
            "Photos on Ahavah need to show you clearly, so the people you meet "
            "here know who they are talking to.",
            "You are welcome to add a new photo of yourself whenever you are "
            "ready. The rest of your profile is unchanged.",
        ],
        button_label="Add a photo",
        button_url=f"{WEB_BASE_URL}/profile/edit",
        cc_admin=False,
    ))
