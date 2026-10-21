"""The note a member gets when one of their photos is taken down (TEC-946).

Built on emails/member_note.py, so it is on the canonical shell with the
"A note from Ahavah." title image. It says three things and nothing else:
what happened, what a profile photo needs, and that they are welcome to add
another. It never says fake and never accuses anyone of anything: a model or
an operator judged a picture, not a person.

Two senders. An admin's Take down sends it straight away
(send_photo_removed). A photo the NSFW cron rejects queues the same note
through email_outbox (queue_for_automatic_rejections), only while the
auto_photo_removed_email switch is on (TEC-1845 admin audit): until then the
cron's takedowns stay silent, as they always were.
"""
from __future__ import annotations

import html as _html
from typing import Iterable

from emails.member_note import FROM_ADDR, member_note_html, send_member_note
from service.config import WEB_BASE_URL

SUBJECT = "About one of your photos"
_PREHEADER = "We have taken one photo down from your profile."
_BUTTON_LABEL = "Add a photo"


def _paragraphs(name: str | None) -> list[str]:
    first = _html.escape((name or '').strip().split(' ')[0])
    greeting = f"Hi {first}," if first else "Hello,"
    return [
        greeting,
        "We have taken one of the photos on your profile down.",
        "Photos on Ahavah need to show you clearly, so the people you meet "
        "here know who they are talking to.",
        "You are welcome to add a new photo of yourself whenever you are "
        "ready. The rest of your profile is unchanged.",
    ]


def send_photo_removed(to_addr: str, name: str | None = None) -> bool:
    """Returns False when the address is suppressed and nothing was sent."""
    return bool(send_member_note(
        to_addr=to_addr,
        subject=SUBJECT,
        preheader=_PREHEADER,
        paragraphs=_paragraphs(name),
        button_label=_BUTTON_LABEL,
        button_url=f"{WEB_BASE_URL}/profile/edit",
        cc_admin=False,
    ))


def photo_removed_html(name: str | None = None) -> str:
    return member_note_html(
        preheader=_PREHEADER,
        paragraphs=_paragraphs(name),
        button_label=_BUTTON_LABEL,
        button_url=f"{WEB_BASE_URL}/profile/edit",
        subject_for_title=SUBJECT,
    )


# The photos among `uuids` the cron itself rejected: rejected with a score
# at or over the cron's threshold. A photo a person took down has no score
# (the cron never scores a decided photo), and the manual route mails it.
_Q_AUTO_REJECTED = """
    SELECT ph.uuid, p.id AS person_id, p.email, p.name
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
     WHERE ph.uuid = ANY(%(uuids)s)
       AND ph.moderation_status = 'rejected'
       AND ph.nsfw_score >= 0.70
"""


def queue_for_automatic_rejections(uuids: Iterable[str]) -> int:
    """Queue the note for each photo in `uuids` the cron rejected. Returns
    how many were queued. Does nothing while the switch is off. One note
    per photo: the outbox key (campaign, campaign_id, person_id) turns a
    second tick over the same photo into nothing. Exempt from the cap, as a
    service note, and the drain still refuses a suppressed address."""
    from database import api_tx
    from service.campaigns import outbox
    from service.campaigns.switches import enabled

    uuids = list(uuids)
    if not uuids or not enabled('auto_photo_removed_email'):
        return 0
    queued = 0
    with api_tx() as tx:
        for r in tx.execute(_Q_AUTO_REJECTED, dict(uuids=uuids)).fetchall():
            if outbox.enqueue(
                    tx, campaign='photo_removed', campaign_id=f"photo_removed-{r['uuid']}",
                    person_id=r['person_id'], email=r['email'], subject=SUBJECT,
                    html=photo_removed_html(r['name']), from_addr=FROM_ADDR,
                    unsub_scope='service', exempt=True) is not None:
                queued += 1
    return queued
