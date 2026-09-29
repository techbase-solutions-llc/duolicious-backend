"""Fail-closed dispatch check (Wave 1 remediation, F02).

The publish worker's very last check before it posts a card to Facebook or
Instagram. `GET /admin/growth/queue/<id>/eligible` delegates to this function
so the answer the worker acts on and the answer this route reports can never
drift apart. Every condition below is checked explicitly; the first failure
wins, and any row this function has not walked all the way to the end
answers False -- there is no path that defaults to True.

Bound to the lease `claim_spotlight_posts` hands out (spec: only the worker
holding the current lease may dispatch a row), to Task 2's immutable
revision (the exact caption/photo/participants a member consented to, not
whatever the mutable queue row now says), and to the two Wave 1 kill
switches. Every function here runs inside the caller's api_tx; none opens
one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from service.spotlight.eligibility import eligibility
from service.spotlight.queue import SUBJECTLESS_KINDS, settings
from service.spotlight.restdays import is_beyond_known, is_rest_period
from service.spotlight.revisions import consent_complete

REASONS = ('not_found', 'not_processing', 'lease_required', 'lease_mismatch', 'lease_expired', 'withdrawn',
           'no_revision', 'not_rendered', 'consent_incomplete', 'subject_missing', 'subject:<reason>',
           'participant:<person_id>:<reason>', 'rest_day', 'calendar_unknown', 'publication_disabled',
           'external_access_disabled')

_Q_ROW = """
    SELECT status, lease_token, (lease_until IS NOT NULL AND lease_until > NOW()) AS lease_valid,
           cancellation_requested_at, current_revision_id, kind, subject_person_id, request_key
      FROM publishing_queue WHERE id = %(id)s
"""

_Q_REVISION = """
    SELECT asset_hash, photo_uuid::text AS photo_uuid, participants
      FROM spotlight_revision WHERE id = %(id)s
"""


def dispatch_check(tx, queue_id, lease_token: Optional[str]) -> tuple[bool, str]:
    row = tx.execute(_Q_ROW, dict(id=queue_id)).fetchone()
    if not row:
        return False, 'not_found'
    if row['status'] != 'processing':
        return False, 'not_processing'
    if not lease_token:
        return False, 'lease_required'
    if lease_token != row['lease_token']:
        return False, 'lease_mismatch'
    if not row['lease_valid']:
        return False, 'lease_expired'
    if row['cancellation_requested_at'] is not None:
        return False, 'withdrawn'
    if row['current_revision_id'] is None:
        return False, 'no_revision'
    rev = tx.execute(_Q_REVISION, dict(id=row['current_revision_id'])).fetchone()
    if not rev or rev['asset_hash'] is None:
        return False, 'not_rendered'
    if not consent_complete(tx, row['current_revision_id']):
        return False, 'consent_incomplete'
    # SUBJECTLESS_KINDS, not `!= 'roundup'`: this line used to read the
    # latter, so the first kind about nobody that was not a roundup (a brand
    # post, TEC-945) would have been refused here as `subject_missing` on
    # every attempt, after the operator had already approved it.
    if row['kind'] not in SUBJECTLESS_KINDS:
        if row['subject_person_id'] is None:
            return False, 'subject_missing'
        ok, reason = eligibility(tx, row['subject_person_id'], rev['photo_uuid'],
                                 exclude_request_key=row['request_key'])
        if not ok:
            return False, f'subject:{reason}'
    else:
        # Count-only (no participants stored) is fine by design; each named
        # participant is re-checked here rather than trusted from creation
        # time, since days can pass between the snapshot and the publish.
        for participant in (rev['participants'] or []):
            person_id = participant.get('person_id')
            # The tile is checked against the photo the TILE shows, never
            # against whatever approved photo the member happens to still
            # have. A participant with no photo_uuid cannot be checked at
            # all, so it fails closed rather than falling back to the
            # has-any-approved-photo test `eligibility` applies when no
            # specific photo is named.
            photo_uuid = participant.get('photo_uuid')
            if not photo_uuid:
                return False, f'participant:{person_id}:photo_missing'
            ok, reason = eligibility(tx, person_id, photo_uuid,
                                     exclude_request_key=row['request_key'])
            if not ok:
                return False, f'participant:{person_id}:{reason}'
    # The last check before anything reaches Meta, whatever way a row came
    # to be due: created before a rest day was entered, approved on an old
    # slot, or rescheduled by hand. The owner's rule is that nothing
    # promotional goes out on a Sabbath or the Day of Atonement, and member
    # cards are as promotional as brand posts, so this applies to every
    # kind. A refusal sends the row back to review with `ineligible:rest_day`
    # on it; nothing is lost, and nothing posts.
    #
    # ITS REACH ENDS AT restdays.KNOWN_THROUGH. The rest days after that date
    # have not been read from the owner's calendar, so for a member card
    # there is nothing to refuse on; that is where member cards stood before
    # this check existed, not a new gap, and it closes as soon as the next
    # month is entered. A brand post is held tighter: nothing about one may
    # be decided past the known calendar (creation and approval refuse it
    # too), so dispatch refuses it there as well.
    now = datetime.now(timezone.utc)
    if is_rest_period(now):
        return False, 'rest_day'
    if row['kind'] == 'brand' and is_beyond_known(now):
        return False, 'calendar_unknown'
    cfg = settings(tx)
    if cfg.get('publication_enabled') != 'true':
        return False, 'publication_disabled'
    if cfg.get('external_access_enabled') != 'true':
        return False, 'external_access_disabled'
    return True, ''
