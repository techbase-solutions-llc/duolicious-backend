"""Admin dashboard — service-layer module.

Every /admin/* endpoint:
  1. Calls require_admin(s) FIRST. Returns 403 for non-admins.
  2. For mutations: calls record_audit(tx, s, action, target, metadata)
     in the SAME api_tx as the mutation so they commit atomically.

Public surface:
  require_admin(s)             — raises HTTPException(403) if not admin
  record_audit(tx, s, ...)     — writes one admin_audit_log row
  record_system_audit(tx, ...) writes one for a cron tick or a command
  is_admin(tx, person_uuid)    — read-only check (used by /admin/whoami)
  require_uuid(value)          — 404 for a path uuid that is not one
  int_arg(name, default, lo, hi) a clamped integer query parameter

Query helpers per tab land in service/admin/queries/* and are
imported here as each phase ships."""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any, Optional

from database import api_tx
from flask import abort
import duotypes as t

from service.admin.queries import Q_IS_ADMIN, Q_INSERT_AUDIT


def is_admin(tx, person_uuid: str) -> bool:
    """1-row gate check. tx is a psycopg cursor owned by the caller."""
    if not person_uuid:
        return False
    row = tx.execute(Q_IS_ADMIN, dict(uuid=person_uuid)).fetchone()
    return bool(row and row.get('is_admin'))


def require_admin(s: t.SessionInfo) -> None:
    """First line of every /admin/* handler. Aborts with 403 if the
    caller's session person_uuid is not in the admin role. Opens its
    own read-only tx — the handler can still open its own write tx."""
    if not s or not s.person_uuid:
        abort(403)
    with api_tx('read committed') as tx:
        if not is_admin(tx, s.person_uuid):
            abort(403)


def require_uuid(value: str) -> str:
    """A path uuid that is not one answers 404, where the ::uuid cast used
    to raise and answer 500 (TEC-1845 admin audit, Minor 26). Returns the
    value unchanged, so the route keeps the text it was given. Call it
    after require_admin, so a non-admin still gets 403."""
    try:
        _uuid.UUID(str(value))
    except ValueError:
        abort(404)
    return value


# The bounds int_arg holds days and page to: a century, and a page past any
# table the admin reads. Both keep make_interval and OFFSET inside int4.
MAX_DAYS = 36500
MAX_PAGE = 1_000_000


def int_arg(name: str, default: int, lo: int, hi: int) -> int:
    """An integer query parameter held to [lo, hi]. A value that is not a
    number reads as the default; one outside the range is clamped, so a
    bookmark with an absurd page or days answers 200 instead of a 500 from
    an interval or bigint overflow (TEC-1845 admin audit, Minor 26)."""
    from flask import request
    try:
        value = int(request.args.get(name, str(default)))
    except ValueError:
        value = default
    return max(lo, min(hi, value))


# An action no admin session made: a cron tick, or a command run on the
# server. admin_audit_log requires an actor uuid and there is no person to
# name, so the nil uuid stands for the system and actor_email says which part
# of it acted ('cron' or 'cli').
SYSTEM_ACTOR_UUID = '00000000-0000-0000-0000-000000000000'


def record_audit(
    tx,
    s: t.SessionInfo,
    action: str,
    target_email: Optional[str] = None,
    target_uuid: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Write one admin_audit_log row. Caller MUST be inside an api_tx
    that also holds the mutation being audited — so the audit + the
    mutation commit (or roll back) together."""
    row = tx.execute(
        Q_INSERT_AUDIT,
        dict(
            actor_email=s.email,
            actor_uuid=s.person_uuid,
            action=action,
            target_email=target_email,
            target_uuid=target_uuid,
            metadata=json.dumps(metadata or {}),
        ),
    ).fetchone()
    return str(row['id'])


def record_system_audit(
    tx,
    actor: str,
    action: str,
    metadata: Optional[dict[str, Any]] = None,
    target_email: Optional[str] = None,
    target_uuid: Optional[str] = None,
) -> str:
    """`record_audit` for an action with no admin session behind it.
    `actor` is 'cron', 'cli' or 'email-link' (a ban or photo deletion made
    from the report email's links, which carry a token and no session).
    Same caller contract: inside the api_tx that holds what is being
    audited, where there is one."""
    row = tx.execute(
        Q_INSERT_AUDIT,
        dict(
            actor_email=actor,
            actor_uuid=SYSTEM_ACTOR_UUID,
            action=action,
            target_email=target_email,
            target_uuid=target_uuid,
            metadata=json.dumps(metadata or {}),
        ),
    ).fetchone()
    return str(row['id'])
