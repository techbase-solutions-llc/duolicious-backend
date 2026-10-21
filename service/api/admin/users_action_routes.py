"""User-management action endpoints. Every mutation is audit-logged.

Endpoints:
  POST   /admin/users/:uuid/entitlements         : grant
  DELETE /admin/users/:uuid/entitlements/:name   : revoke
  POST   /admin/users/:uuid/tokens               : manual credit/debit
  PATCH  /admin/users/:uuid/roles                : grant/revoke admin/mod
  POST   /admin/users/:uuid/deactivate           : soft delete
  POST   /admin/users/:uuid/reactivate           : undo soft delete
  DELETE /admin/users/:uuid                      : hard delete (requires confirm_email)
  POST   /admin/users/:uuid/clear-onboardee      : wipe onboardee + sessions

Every mutation calls require_admin(s) FIRST, then performs the mutation
and writes one admin_audit_log row in the same api_tx EXCEPT for the
two entitlement endpoints, since service.entitlements.grant/revoke open
their own tx, so the audit is written in an adjacent tx. Acceptable
trade-off because entitlements grant/revoke is idempotent.
"""
from __future__ import annotations

import duotypes as t
from flask import abort

from service.api.decorators import apost, apatch, adelete, validate
from service.admin import require_admin, record_audit
from service import entitlements
from service.tokens import (
    InsufficientTokens,
    credit as tokens_credit,
    debit as tokens_debit,
)
from database import api_tx
from antiabuse.antispam.signupemail import normalize_email
from service.spotlight.withdrawal import withdraw_member
from service.hard_delete import (
    Q_DELETE_BETA_SIGNUP_OF,
    Q_DELETE_EVENT_DATA_OF,
    Q_DELETE_INBOX_OF,
    Q_DELETE_LEADS_OF,
    Q_DELETE_MATCHMAKER_DATA_OF,
    Q_DELETE_TOOL_DATA_OF,
    Q_DELETE_WAITLIST_OF,
    matchmaker_keys,
    Q_PURGE_HELD_MESSAGES_OF,
    Q_STAGE_AUDIO_FOR_REMOVAL,
    Q_STAGE_PHOTOS_FOR_REMOVAL,
)
from service.referrals import Q_FORGET_CLICK_INVITER, Q_PURGE_REFERRALS_OF


# ----- helpers -------------------------------------------------------------

_Q_PERSON_BY_UUID = """
    SELECT id, uuid::text AS uuid, email, COALESCE(roles, ARRAY[]::text[]) AS roles
      FROM person WHERE uuid = %(uuid)s::uuid
"""

_Q_SOFT_DELETE = """
    WITH deactivated AS (
        -- admin_deactivated_at is what keeps the member out: the sign-in
        -- queries refuse it, while activated alone is set back to TRUE by
        -- the next sign-in.
        UPDATE person SET activated = FALSE, admin_deactivated_at = NOW()
         WHERE uuid = %(uuid)s::uuid
        RETURNING id, email
    ),
    del_session AS (
        DELETE FROM duo_session
         WHERE person_id IN (SELECT id FROM deactivated)
    )
    SELECT email FROM deactivated
"""

_Q_REACTIVATE = """
    WITH before_state AS (
        SELECT id, activated FROM person WHERE uuid = %(uuid)s::uuid
    ),
    reactivated AS (
        UPDATE person SET
            activated = TRUE,
            admin_deactivated_at = NULL,
            -- Pull them out of autodeactivate2's 30-50 day window, or the
            -- cron reverts this within one 300s poll (F14).
            last_online_time = NOW()
        WHERE uuid = %(uuid)s::uuid
        RETURNING id, email
    ),
    -- Mirrors Q_MAYBE_SIGN_IN's club_to_increment CTE: only restore the
    -- count if the row was NOT already activated, so a repeat reactivate
    -- call (or a race) can't double-increment.
    club_to_increment AS (
        SELECT person_club.club_name
        FROM reactivated
        JOIN before_state ON before_state.id = reactivated.id
        JOIN person_club ON person_club.person_id = reactivated.id
        WHERE NOT before_state.activated
    ),
    increment_club_count AS (
        UPDATE club SET
            count_members = count_members + 1
        FROM club_to_increment
        WHERE club_to_increment.club_name = club.name
    )
    SELECT email FROM reactivated
"""

_Q_HARD_DELETE = """
    DELETE FROM person WHERE uuid = %(uuid)s::uuid
    RETURNING email, uuid::text AS uuid
"""

_Q_PATCH_ROLES = """
    UPDATE person
       SET roles = %(roles)s
     WHERE uuid = %(uuid)s::uuid
    RETURNING email, roles
"""

# Wipe onboardee + any duo_session rows tied to the person's email. The
# WITH clause runs first; the final DELETE returns the email for audit.
_Q_CLEAR_ONBOARDEE = """
    WITH target AS (
        SELECT email FROM person WHERE uuid = %(uuid)s::uuid
    ),
    del_session AS (
        DELETE FROM duo_session
         WHERE email IN (SELECT email FROM target)
        RETURNING email
    )
    DELETE FROM onboardee
     WHERE email IN (SELECT email FROM target)
    RETURNING email
"""


# ----- ENTITLEMENTS --------------------------------------------------------

@apost('/admin/users/<uuid>/entitlements')
@validate(t.PostGrantEntitlement)
def post_grant_entitlement(req: t.PostGrantEntitlement, s: t.SessionInfo, uuid: str):
    require_admin(s)
    # service.entitlements.grant takes int person.id, not uuid, so look up first.
    with api_tx('read committed') as tx:
        row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
    if row is None:
        abort(404)
    person_id = int(row['id'])
    target_email = row['email']
    # grant() opens its OWN api_tx; we cannot piggyback the audit on it.
    # If the process dies between these two statements the entitlement
    # change is silently un-audited. Acceptable because grant is idempotent.
    changed = entitlements.grant(person_id, req.name, expires_at=req.expires_at)
    with api_tx() as tx:
        record_audit(
            tx, s, 'grant_entitlement',
            target_email=target_email, target_uuid=uuid,
            metadata={
                'name': req.name,
                'expires_at': req.expires_at.isoformat() if req.expires_at else None,
                'reason': req.reason,
                'changed': changed,
            },
        )
    return {'ok': True, 'changed': changed}


@adelete('/admin/users/<uuid>/entitlements/<name>')
def delete_revoke_entitlement(s: t.SessionInfo, uuid: str, name: str):
    require_admin(s)
    with api_tx('read committed') as tx:
        row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
    if row is None:
        abort(404)
    person_id = int(row['id'])
    target_email = row['email']
    # revoke() opens its OWN api_tx, the same caveat as grant() above.
    changed = entitlements.revoke(person_id, name)
    with api_tx() as tx:
        record_audit(
            tx, s, 'revoke_entitlement',
            target_email=target_email, target_uuid=uuid,
            metadata={'name': name, 'changed': changed},
        )
    return {'ok': True, 'changed': changed}


# ----- TOKENS --------------------------------------------------------------

@apost('/admin/users/<uuid>/tokens')
@validate(t.PostTokenAdjust)
def post_token_adjust(req: t.PostTokenAdjust, s: t.SessionInfo, uuid: str):
    require_admin(s)
    if req.delta == 0:
        abort(400)
    try:
        with api_tx() as tx:
            row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
            if row is None:
                abort(404)
            target_email = row['email']
            amount = abs(req.delta)
            if req.delta > 0:
                tokens_credit(
                    tx, uuid, amount,
                    reason='admin_credit',
                    metadata={'admin': s.email, 'reason': req.reason},
                )
            else:
                tokens_debit(
                    tx, uuid, amount,
                    reason='admin_debit',
                    metadata={'admin': s.email, 'reason': req.reason},
                )
            record_audit(
                tx, s, 'token_adjust',
                target_email=target_email, target_uuid=uuid,
                metadata={'delta': req.delta, 'reason': req.reason},
            )
    except InsufficientTokens:
        # Raised before the ledger insert; leaving the with block by the
        # exception rolls the transaction back, so nothing is written.
        return dict(error='insufficient_tokens'), 409
    return {'ok': True, 'delta': req.delta}


# ----- ROLES ---------------------------------------------------------------

@apatch('/admin/users/<uuid>/roles')
@validate(t.PatchRoles)
def patch_roles(req: t.PatchRoles, s: t.SessionInfo, uuid: str):
    require_admin(s)
    allowed = {'admin', 'mod'}
    add = [r for r in req.add if r in allowed]
    remove = [r for r in req.remove if r in allowed]
    with api_tx() as tx:
        row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
        if row is None:
            abort(404)
        target_email = row['email']
        current = set(row['roles'] or [])
        before = sorted(current)
        new = sorted((current - set(remove)) | set(add))
        updated = tx.execute(
            _Q_PATCH_ROLES, dict(uuid=uuid, roles=new),
        ).fetchone()
        record_audit(
            tx, s, 'patch_roles',
            target_email=target_email, target_uuid=uuid,
            metadata={'before': before, 'after': new, 'reason': req.reason},
        )
    return {'ok': True, 'roles': list(updated['roles'])}


# ----- LIFECYCLE -----------------------------------------------------------

@apost('/admin/users/<uuid>/deactivate')
@validate(t.PostLifecycle)
def post_deactivate_admin(req: t.PostLifecycle, s: t.SessionInfo, uuid: str):
    require_admin(s)
    with api_tx() as tx:
        person_row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
        if person_row is None:
            abort(404)
        # Deactivate now blocks sign-in until an admin reactivates, and it
        # deletes the caller's sessions with the rest, so an admin who
        # deactivated their own account would be locked out of the admin
        # with nobody left to reactivate them. Refused before any write.
        if s.person_id is not None and int(person_row['id']) == int(s.person_id):
            return dict(error='cannot_deactivate_self'), 409
        # Wave 1 F03: withdraw Spotlight before the deactivation below takes
        # effect, in the same transaction -- a deactivated member must not
        # stay queued or published.
        withdraw_member(tx, int(person_row['id']), 'admin_delete')
        row = tx.execute(_Q_SOFT_DELETE, dict(uuid=uuid)).fetchone()
        if row is None:
            abort(404)
        record_audit(
            tx, s, 'deactivate',
            target_email=row['email'], target_uuid=uuid,
            metadata={'reason': req.reason},
        )
    return {'ok': True}


@apost('/admin/users/<uuid>/reactivate')
@validate(t.PostLifecycle)
def post_reactivate(req: t.PostLifecycle, s: t.SessionInfo, uuid: str):
    require_admin(s)
    with api_tx() as tx:
        row = tx.execute(_Q_REACTIVATE, dict(uuid=uuid)).fetchone()
        if row is None:
            abort(404)
        record_audit(
            tx, s, 'reactivate',
            target_email=row['email'], target_uuid=uuid,
            metadata={'reason': req.reason},
        )
    return {'ok': True}


@adelete('/admin/users/<uuid>')
@validate(t.DeletePerson)
def delete_person(req: t.DeletePerson, s: t.SessionInfo, uuid: str):
    require_admin(s)
    with api_tx() as tx:
        row = tx.execute(_Q_PERSON_BY_UUID, dict(uuid=uuid)).fetchone()
        if row is None:
            abort(404)
        if (row['email'] or '').strip().lower() != req.confirm_email.strip().lower():
            # Hard delete is irreversible, so the safety gate is a string
            # match against the stored email, so a typo or stale UI state
            # can't cascade-wipe the wrong row. FK cascade handles photos,
            # likes, messages, sessions, etc.
            abort(400)
        # Wave 1 F03: withdraw Spotlight before the hard-delete below removes
        # the row -- the removal task's own person_id/request_key columns
        # are what survives to tell the admin worker who it was for.
        withdraw_member(tx, int(row['id']), 'admin_delete')
        # Nothing cascades from person to the referral tables (migration
        # 0037), so the address is cleared here, as the deletion cron does
        # (service/cron/pendingdeletion). Until 13 Oct 2026 this route left
        # it in both.
        if row['email']:
            emails = [row['email']]
            tx.execute(Q_PURGE_REFERRALS_OF, dict(emails=emails))
            tx.execute(Q_FORGET_CLICK_INVITER, dict(emails=emails))
        # The member's photos and voice recording go to the CDN cleaners'
        # queues before the cascade removes the rows that name them, and
        # their inbox, waitlist and beta rows (no cascade) go with them, as
        # in the deletion cron. Until 13 Oct 2026 this route did none of it,
        # so the files stayed fetchable.
        person_ids = [int(row['id'])]
        tx.execute(Q_STAGE_PHOTOS_FOR_REMOVAL, dict(ids=person_ids))
        tx.execute(Q_STAGE_AUDIO_FOR_REMOVAL, dict(ids=person_ids))
        # Unmatch (TEC-1845): both sides of any held conversation, before the
        # cascade, as the deletion cron does. Bound with the stored uuid, not
        # the path: ::uuid finds a uuid typed without hyphens or in capitals,
        # and the held rows name the person by its canonical text.
        tx.execute(Q_PURGE_HELD_MESSAGES_OF, dict(ids=person_ids, uuids=[row['uuid']]))
        # Together (TEC-1845), before the person delete: a guest's seat
        # cascades off person, and the shared game is found by it.
        tx.execute(Q_DELETE_TOOL_DATA_OF, dict(
            nes=[normalize_email(row['email'])] if row['email'] else [], ids=person_ids))
        # Gatherings (TEC-1845): the account's RSVPs, before the person
        # delete sets their person_id to NULL.
        tx.execute(Q_DELETE_EVENT_DATA_OF, dict(
            nes=[normalize_email(row['email'])] if row['email'] else [], ids=person_ids))
        # Matchmaker (TEC-1845), before the person delete.
        _nes = [normalize_email(row['email'])] if row['email'] else []
        tx.execute(Q_DELETE_MATCHMAKER_DATA_OF, dict(nes=_nes, ids=person_ids, keys=matchmaker_keys(_nes)))
        del_row = tx.execute(_Q_HARD_DELETE, dict(uuid=uuid)).fetchone()
        tx.execute(Q_DELETE_INBOX_OF, dict(uuids=[del_row['uuid']]))
        if row['email']:
            tx.execute(Q_DELETE_WAITLIST_OF, dict(emails=[row['email']]))
            tx.execute(Q_DELETE_BETA_SIGNUP_OF, dict(emails=[row['email']]))
            tx.execute(Q_DELETE_LEADS_OF, dict(nes=[normalize_email(row['email'])]))
        record_audit(
            tx, s, 'hard_delete',
            target_email=del_row['email'], target_uuid=uuid,
            metadata={'reason': req.reason},
        )
    return {'ok': True}


# ----- SUPPORT / DEBUG -----------------------------------------------------

@apost('/admin/users/<uuid>/clear-onboardee')
@validate(t.PostLifecycle)
def post_clear_onboardee(req: t.PostLifecycle, s: t.SessionInfo, uuid: str):
    require_admin(s)
    with api_tx() as tx:
        row = tx.execute(_Q_CLEAR_ONBOARDEE, dict(uuid=uuid)).fetchone()
        record_audit(
            tx, s, 'clear_onboardee',
            target_email=(row or {}).get('email'), target_uuid=uuid,
            metadata={'reason': req.reason},
        )
    return {'ok': True}
