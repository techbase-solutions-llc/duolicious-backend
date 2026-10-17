"""Together's sweep (TEC-1845), run daily by the lead retention cron.

  - A saved session (or one a member started) goes 12 months after the
    last visit by a player (service.leads.RETENTION_DAYS, the leads'
    clock). A visit is any read or write with a player's token or saved
    address (service/tools/sessions.player_for); opening a share link is
    not a visit.
  - A session nobody saved goes after UNSAVED_DAYS: nothing links it to
    anyone but a device.
  - A deleted session's tombstone (its tokens, so links say "deleted")
    goes TOMBSTONE_DAYS after the delete.
Players, answers and results go with their session (ON DELETE CASCADE).
"""
from __future__ import annotations

from service.leads import RETENTION_DAYS

UNSAVED_DAYS = 30
TOMBSTONE_DAYS = 30

_Q_PURGE = """
    DELETE FROM tool_session
     WHERE (deleted_at IS NOT NULL
            AND deleted_at < NOW() - make_interval(days => %(tomb)s))
        OR (deleted_at IS NULL AND claimed_at IS NULL AND owner_person_id IS NULL
            AND last_visit_at < NOW() - make_interval(days => %(unsaved)s))
        OR (deleted_at IS NULL
            AND last_visit_at < NOW() - make_interval(days => %(days)s))
"""


def purge_stale_tool_sessions(tx) -> int:
    return tx.execute(_Q_PURGE, dict(tomb=TOMBSTONE_DAYS, unsaved=UNSAVED_DAYS,
                                     days=RETENTION_DAYS)).rowcount
