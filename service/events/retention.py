"""Gathering retention (TEC-1845), run daily by the lead retention cron
(service/cron/leadretention), and the account's share of it.

  - A guest's name and email are erased ERASE_AFTER_END after the
    gathering ends; the row stays, so the counts do (party size, confirmed,
    attended).
  - An RSVP never confirmed goes a day after its confirm window closes.
  - An organiser's magic link goes a day after it lapses.
  - A leader's invite request goes INVITE_RETENTION after its last change.
  - Deleting an account deletes its RSVPs (Q_DELETE_EVENT_DATA_OF).
    Organisers are not accounts and stay while they host; the privacy page
    says to ask support.

The RSVP's lead (event:{slug}) keeps the leads' own clock.
"""
from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

ERASE_AFTER_END = timedelta(days=90)
UNCONFIRMED_GRACE = timedelta(days=1)
LINK_GRACE = timedelta(days=1)
INVITE_RETENTION = timedelta(days=365)

_Q_ERASE = """
    UPDATE event_rsvp r
       SET name = NULL, email = NULL, normalized_email = NULL, token_hash = NULL, erased_at = %(now)s
      FROM event e
     WHERE e.id = r.event_id AND r.erased_at IS NULL AND e.ends_at < %(now)s - %(after)s
"""

_Q_UNCONFIRMED = """
    DELETE FROM event_rsvp
     WHERE confirmed_at IS NULL AND erased_at IS NULL AND confirm_by < %(now)s - %(grace)s
"""

_Q_LINKS = "DELETE FROM organiser_link WHERE expires_at < %(now)s - %(grace)s"

_Q_REQUESTS = "DELETE FROM ahavah_invite_request WHERE updated_at < %(now)s - %(keep)s"


def purge_event_data(tx, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return dict(
        erased=tx.execute(_Q_ERASE, dict(now=now, after=ERASE_AFTER_END)).rowcount,
        unconfirmed=tx.execute(_Q_UNCONFIRMED, dict(now=now, grace=UNCONFIRMED_GRACE)).rowcount,
        links=tx.execute(_Q_LINKS, dict(now=now, grace=LINK_GRACE)).rowcount,
        requests=tx.execute(_Q_REQUESTS, dict(now=now, keep=INVITE_RETENTION)).rowcount)


# Every RSVP the address or the account made. The caller binds `nes`, as
# for service.hard_delete.Q_DELETE_LEADS_OF (each address through antiabuse
# normalize_email; an empty list when there is none), and `ids`, the person
# ids. Runs before the person delete: event_rsvp.person_id is SET NULL, so
# after it an RSVP made with another address is no longer found.
Q_DELETE_EVENT_DATA_OF = """
    DELETE FROM event_rsvp
     WHERE normalized_email = ANY(%(nes)s::text[])
        OR person_id = ANY(%(ids)s::int[])
"""


def link_rsvps_to_person(tx, person_id: int) -> None:
    """At finish-onboarding: the new member's confirmed RSVPs, made with
    their address before they joined, become theirs, so they go with the
    account. The member's lead_source of event:{slug} comes from
    link_leads_to_person, which runs first. Rolled back to a savepoint and
    ignored on any failure, so it can never undo the sign-up."""
    tx.execute('SAVEPOINT link_rsvps')
    try:
        tx.execute(
            """UPDATE event_rsvp SET person_id = %(pid)s
                WHERE normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
                  AND confirmed_at IS NOT NULL AND person_id IS NULL""",
            dict(pid=person_id))
    except Exception:
        print(traceback.format_exc())
        tx.execute('ROLLBACK TO SAVEPOINT link_rsvps')
    else:
        tx.execute('RELEASE SAVEPOINT link_rsvps')
