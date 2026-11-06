"""Format-only redraw of an approved member card (TEC-2113,
docs/plans/2026-11-06-spotlight-format-redraw.md).

The owner, 6 Nov 2026: member cards move from 1080x1080 to 4:5, and an
approved card is redrawn without asking the member again ("it's just an
aspect ratio fix"). So this is the one path where a request's artwork bytes
change and its revision does not: same revision id, caption, photo,
participants and channels, so the consent recorded against that revision
stays valid. Nothing here queues an email or a push.

While a redraw is pending every row of the request carries
`format_redraw_requested_at`, and `claim_spotlight_posts` (migration 0096)
skips it, so neither the old artwork nor a half-redrawn pair can be
published. Each row keeps its old artwork until its own new artwork lands,
in one UPDATE, so a row is never without an image. Once every held row
carries the same new bytes, the revision is pointed at them and the hold
comes off; the row's status and `scheduled_for` are never touched, so a
slot that passed while the redraw was pending is claimed by the next publish
run (late, never square).

Every function here runs inside the caller's api_tx; none opens one, and
none calls storage.
"""
from __future__ import annotations

from typing import Optional

from service.spotlight.cleanup import enqueue_asset_delete, is_referenced
from service.spotlight.revisions import consent_complete

# The kinds the tick draws from a member's photo with their consent. Roundups
# and Ahavah's own posts keep their usual path.
MEMBER_CARD_KINDS = ('welcome', 'member_of_week')
# An approved card: consented, and either waiting for the admin's approval or
# approved onto a slot. Nothing else may be redrawn.
REDRAWABLE = ('review', 'scheduled')
TERMINAL = ('published', 'cancelled')
UNRESOLVED_DELIVERY = ('attempting', 'delivery_unknown')

_Q_LOCK_REQUEST = """
    SELECT id, request_key, platform, kind, status, delivery_state, cancellation_requested_at,
           current_revision_id, image_key, format_redraw_requested_at
      FROM publishing_queue
     WHERE request_key = (SELECT request_key FROM publishing_queue WHERE id = %(id)s)
     ORDER BY id
     FOR UPDATE
"""

# The conditions every write below repeats, so a row that moved on between
# the request and the upload (cancelled, withdrawn, re-revisioned, claimed)
# is never written. `{q}` is the alias of the row being written.
_HELD = """{q}format_redraw_requested_at IS NOT NULL
       AND {q}kind IN ('welcome', 'member_of_week')
       AND {q}status IN ('review', 'scheduled')
       AND {q}cancellation_requested_at IS NULL
       AND ({q}delivery_state IS NULL OR {q}delivery_state NOT IN ('attempting', 'delivery_unknown'))"""

_Q_TARGET = f"""
    SELECT current_revision_id FROM publishing_queue q
     WHERE request_key = %(rk)s AND platform = %(pl)s AND {_HELD.format(q='q.')}
"""

# Compare and set, the shape `assets.attach_platform_image` uses: the old key
# is read through a `FOR UPDATE` CTE in the same statement, and the row is
# written only while it is still held on the same, already rendered revision.
_Q_ATTACH = f"""
    WITH prev AS (
        SELECT id, image_key FROM publishing_queue
         WHERE request_key = %(rk)s AND platform = %(pl)s
           FOR UPDATE
    )
    UPDATE publishing_queue
       SET image_key = %(k)s, image_url = %(u)s, image_sha256 = %(h)s, updated_at = NOW()
      FROM prev
     WHERE publishing_queue.id = prev.id
       AND publishing_queue.current_revision_id = %(rev)s
       AND {_HELD.format(q='publishing_queue.')}
       AND EXISTS (SELECT 1 FROM spotlight_revision r
                    WHERE r.id = %(rev)s AND r.asset_hash IS NOT NULL)
 RETURNING prev.image_key AS previous_key
"""

_Q_HELD_ROWS = f"""
    SELECT id, platform, status, scheduled_for, image_key, image_url, image_sha256,
           (scheduled_for IS NOT NULL AND scheduled_for < NOW()) AS past_slot
      FROM publishing_queue q
     WHERE request_key = %(rk)s AND current_revision_id = %(rev)s AND {_HELD.format(q='q.')}
     ORDER BY id
     FOR UPDATE
"""


def lock_request(tx, queue_id) -> list:
    """Every row of the request the given queue row belongs to, locked in id
    order, the order `queue.lock_request_rows` takes them in."""
    return tx.execute(_Q_LOCK_REQUEST, dict(id=queue_id)).fetchall()


def request_format_redraw(tx, rows: list) -> dict:
    """Hold every row of one request for a format-only redraw of its current
    revision. `rows` is `lock_request`'s answer. Raises ValueError with the
    first reason that refuses it: not_found, not_member_card, terminal,
    bad_status, delivery_unresolved, withdrawn, not_approved.

    Returns `already` (every row was held before this call, nothing
    written), `held` (how many rows are held), `revision_id`, and `old_keys`
    (each platform's artwork as it is now), for the caller's audit row."""
    if not rows:
        raise ValueError('not_found')
    if any(r['kind'] not in MEMBER_CARD_KINDS for r in rows):
        raise ValueError('not_member_card')
    if any(r['status'] in TERMINAL for r in rows):
        raise ValueError('terminal')
    if any(r['status'] not in REDRAWABLE for r in rows):
        raise ValueError('bad_status')
    if any(r['delivery_state'] in UNRESOLVED_DELIVERY for r in rows):
        raise ValueError('delivery_unresolved')
    if any(r['cancellation_requested_at'] is not None for r in rows):
        raise ValueError('withdrawn')
    revision_ids = {r['current_revision_id'] for r in rows}
    revision_id = revision_ids.pop() if len(revision_ids) == 1 else None
    if revision_id is None:
        raise ValueError('not_approved')
    rendered = tx.execute("SELECT asset_hash FROM spotlight_revision WHERE id = %(id)s",
                          dict(id=revision_id)).fetchone()
    if not rendered or rendered['asset_hash'] is None or not consent_complete(tx, revision_id):
        raise ValueError('not_approved')
    waiting = [r['id'] for r in rows if r['format_redraw_requested_at'] is None]
    if waiting:
        tx.execute(
            """UPDATE publishing_queue SET format_redraw_requested_at = NOW(), updated_at = NOW()
                WHERE id = ANY(%(ids)s)""",
            dict(ids=waiting))
    return dict(already=not waiting, held=len(rows), revision_id=revision_id,
                old_keys={r['platform']: r['image_key'] for r in rows})


def redraw_target(tx, request_key: str, platform: str) -> Optional[int]:
    """The revision a held row's new artwork is drawn for, or None when this
    platform row is not held (no redraw asked for, or it has moved on)."""
    row = tx.execute(_Q_TARGET, dict(rk=request_key, pl=platform)).fetchone()
    return row['current_revision_id'] if row else None


def attach_redraw_image(tx, request_key: str, platform: str, revision_id: int,
                        key: str, url: str, sha256: str) -> tuple[str, Optional[str]]:
    """Replace one held row's artwork with the redraw. Returns ('attached',
    the key it displaced) or ('superseded', None) when the row is no longer
    held on that revision, in which case nothing was written.

    A displaced key nothing else names is queued for deletion here. The
    first platform's old key is usually still named by the revision, so it
    survives until `finish_format_redraw` moves the revision off it."""
    row = tx.execute(_Q_ATTACH, dict(rk=request_key, pl=platform, rev=revision_id,
                                     k=key, u=url, h=sha256)).fetchone()
    if not row:
        return 'superseded', None
    previous = row['previous_key']
    if previous and previous != key and not is_referenced(tx, previous):
        enqueue_asset_delete(tx, previous)
    return 'attached', previous


def ready_to_finish(tx, request_key: str, revision_id: int, sha256: str) -> Optional[list]:
    """None until every held row carries these bytes. Then the keys that
    must be public before the hold comes off: those of the rows already
    approved onto a slot. A row still in review is made public by its own
    approval, as before."""
    rows = tx.execute(_Q_HELD_ROWS, dict(rk=request_key, rev=revision_id)).fetchall()
    if not rows or any(r['image_sha256'] != sha256 or not r['image_key'] for r in rows):
        return None
    return [r['image_key'] for r in rows if r['status'] == 'scheduled']


def finish_format_redraw(tx, request_key: str, revision_id: int, sha256: str) -> Optional[dict]:
    """Point the revision at the new render and take the hold off, once,
    under the same conditions `ready_to_finish` checked (re-read under the
    row locks, since storage calls ran in between). Returns None when the
    set moved on; otherwise what the audit row records.

    The revision is pinned to the facebook row's key when there is one, as
    `assets.complete_render_if_ready` pins it. Its previous key is queued
    for deletion unless something (a published row) still names it."""
    rows = tx.execute(_Q_HELD_ROWS, dict(rk=request_key, rev=revision_id)).fetchall()
    if not rows or any(r['image_sha256'] != sha256 or not r['image_key'] for r in rows):
        return None
    pinned = next((r for r in rows if r['platform'] == 'facebook'), rows[0])
    previous = tx.execute("SELECT image_key FROM spotlight_revision WHERE id = %(id)s",
                          dict(id=revision_id)).fetchone()['image_key']
    tx.execute(
        """UPDATE spotlight_revision SET asset_hash = %(h)s, image_key = %(k)s, image_url = %(u)s
            WHERE id = %(id)s""",
        dict(h=sha256, k=pinned['image_key'], u=pinned['image_url'], id=revision_id))
    tx.execute(
        """UPDATE publishing_queue SET format_redraw_requested_at = NULL, updated_at = NOW()
            WHERE id = ANY(%(ids)s)""",
        dict(ids=[r['id'] for r in rows]))
    if previous and previous != pinned['image_key'] and not is_referenced(tx, previous):
        enqueue_asset_delete(tx, previous)
    scheduled = [r for r in rows if r['status'] == 'scheduled']
    return dict(
        revision_id=revision_id,
        new_keys={r['platform']: r['image_key'] for r in rows},
        previous_revision_key=previous,
        statuses={r['platform']: r['status'] for r in rows},
        scheduled_for={r['platform']: r['scheduled_for'].isoformat() for r in scheduled
                       if r['scheduled_for'] is not None},
        # The slot passed while the redraw was pending: the row is due, so the
        # next publish run claims it. Late, never square.
        late=any(r['past_slot'] for r in scheduled),
    )
