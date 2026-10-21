"""
service.moderation - admin/mod-gated abuse-report listing.

Phase W cutover (2026-05-15) closes the gap that DUO_REPORT_EMAIL
points at placeholder bouncing addresses (ahavah@example.com etc).
Until that env points at a real mailbox, abuse reports persist only
in the database: the `skipped` row with `reported = TRUE` (which is also
the block) and, since migration 0072, a `person_report` row per report
filed, which outlives an unblock. This module surfaces those reports to operators with `admin` or `mod` in
person.roles via GET /admin/reports.

Auth model:
- Standard session check via the @aget decorator (must be signed in
  + onboarded — abuse moderation can't be done by anonymous viewers).
- Role gate inside the handler: person.roles && ARRAY['admin','mod'].
  Returns 403 for non-admin signed-in users.

Resolving (TEC-1897): POST /admin/reports/<report_key>/resolve records an
outcome, a note, who and when on the report's own person_report row
(migration 0074). A report made again on the same pair is a new row (the
skip upsert moves created_at and the 0072 trigger files it), so it starts
unresolved. The member's reason is never copied into the outcome, the
audit row or any email.

"Email me when a report arrives" (admin_alert_pref, migration 0074) is the
owner's switch for the report email antiabuse/lodgereport sends.
"""

import re

from database import api_tx


# ---------------------------------------------------------------------------
# Q_IS_ADMIN_OR_MOD - 1-row gate-check used by every handler in this module
# ---------------------------------------------------------------------------
Q_IS_ADMIN_OR_MOD = """
SELECT 1
  FROM person
 WHERE id = %(person_id)s
   AND roles && ARRAY['admin', 'mod']::TEXT[]
"""


# ---------------------------------------------------------------------------
# Q_LIST_REPORTS - reporter + reported user info + reason + age
# ---------------------------------------------------------------------------
#
# Reads person_report (migration 0072), one row per report filed, joined
# to the REPORTER and the REPORTED. It used to read `skipped` WHERE
# reported, which is also the block, so a reporter who unblocked deleted
# the report from this list (TEC-1845 admin audit). An unblock now lifts the
# block and leaves the report here.
#
# Limit 200 - if you have more than 200 outstanding moderation actions,
# you need a real ticketing tool, not a SQL view.

# A report is identified by its pair and its own time (TEC-1897): the key
# is the reporter's id, the reported member's id and reported_at to the
# microsecond, the primary key of person_report.
_REPORT_KEY = ("r.reporter_id || '-' || r.reported_id || '-' || "
               "to_char(r.reported_at, 'YYYYMMDDHH24MISSUS')")

Q_LIST_REPORTS = f"""
SELECT
    r.reported_at::text                          AS created_at,
    {_REPORT_KEY}                                AS report_key,
    r.reporter_id                                AS reporter_id,
    reporter.uuid::text                          AS reporter_uuid,
    reporter.name                                AS reporter_name,
    reporter.email                               AS reporter_email,
    r.reported_id                                AS reported_id,
    reported.uuid::text                          AS reported_uuid,
    reported.name                                AS reported_name,
    reported.email                               AS reported_email,
    reported.activated                           AS reported_active,
    reported.verification_required               AS reported_verification_required,
    r.reason                                     AS reason,
    r.outcome                                    AS outcome,
    r.note                                       AS note,
    r.resolved_at                                AS resolved_at,
    split_part(resolver.name, ' ', 1)            AS resolved_by_name
FROM   person_report r
JOIN   person reporter ON reporter.id = r.reporter_id
JOIN   person reported ON reported.id = r.reported_id
LEFT JOIN person resolver ON resolver.uuid = r.resolved_by_uuid
ORDER BY r.reported_at DESC
LIMIT 200
"""

# Overview's Needs you band (TEC-1897). Reads the partial index
# idx__person_report__unresolved.
Q_COUNT_UNRESOLVED = """
SELECT count(*)::int AS n FROM person_report WHERE outcome IS NULL
"""

OUTCOMES = ('dismissed', 'warned', 'deactivated')
NOTE_MAX = 1000

_KEY_RE = re.compile(r'^(\d{1,10})-(\d{1,10})-(\d{20})$')

_Q_RESOLVE = """
UPDATE person_report
   SET outcome = %(outcome)s, note = %(note)s, resolved_at = NOW(),
       resolved_by_uuid = %(by_uuid)s, resolved_by_email = %(by_email)s
 WHERE reporter_id = %(a)s AND reported_id = %(b)s
   AND to_char(reported_at, 'YYYYMMDDHH24MISSUS') = %(ts)s
   AND outcome IS NULL
RETURNING reporter_id
"""

_Q_REPORT_EXISTS = """
SELECT 1 FROM person_report
 WHERE reporter_id = %(a)s AND reported_id = %(b)s
   AND to_char(reported_at, 'YYYYMMDDHH24MISSUS') = %(ts)s
"""


def parse_report_key(key: str):
    m = _KEY_RE.match(key or '')
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def unresolved_count(tx) -> int:
    return tx.execute(Q_COUNT_UNRESOLVED).fetchone()['n']


def resolve_report(tx, key: str, outcome: str, note: str, by_uuid: str, by_email: str) -> str:
    """'resolved', 'not_found' or 'already_resolved'. The caller has checked
    the outcome and the note's length and holds the transaction."""
    parsed = parse_report_key(key)
    if parsed is None:
        return 'not_found'
    a, b, ts = parsed
    params = dict(a=a, b=b, ts=ts, outcome=outcome, note=note, by_uuid=by_uuid, by_email=by_email)
    if tx.execute(_Q_RESOLVE, params).fetchone():
        return 'resolved'
    return 'already_resolved' if tx.execute(_Q_REPORT_EXISTS, params).fetchone() else 'not_found'


def report_email_on() -> bool:
    """The owner's "Email me when a report arrives" (TEC-1897). On unless he
    turned it off: no row reads as on, and so does a preference that cannot
    be read, because the report email was live before the switch and a
    database fault must never silence a report."""
    try:
        with api_tx('read committed') as tx:
            row = tx.execute(
                "SELECT enabled FROM admin_alert_pref WHERE alert = 'report'").fetchone()
        return True if row is None else bool(row['enabled'])
    except Exception as e:
        print(f'report_email_on: preference not read, sending ({type(e).__name__})')
        return True


def get_admin_reports(s):
    """Returns recent abuse reports for admin/mod review.

    Response shape:
      200: {"reports": [{...}, ...], "count": N}
      401: not signed in
      403: signed in but not admin/mod

    Each report dict carries:
      created_at, reporter_id, reporter_uuid, reporter_name,
      reporter_email, reported_id, reported_uuid, reported_name,
      reported_email, reported_active, reported_verification_required,
      reason, report_key, outcome, note, resolved_at, resolved_by_name
    """
    if not s or not s.person_id:
        return 'Not authorized', 401

    with api_tx('read committed') as tx:
        is_admin = tx.execute(
            Q_IS_ADMIN_OR_MOD,
            dict(person_id=s.person_id),
        ).fetchone()
        if not is_admin:
            return 'Forbidden', 403

        rows = tx.execute(Q_LIST_REPORTS).fetchall()
        unresolved = unresolved_count(tx)

    # `count` is every report listed, so an empty list doesn't look like a
    # fetch failure; `unresolved` is what Overview's Needs you band counts
    # (TEC-1897). resolved_at leaves as ISO 8601, never Flask's RFC 2822.
    return {
        'reports': [dict(r, resolved_at=r['resolved_at'].isoformat() if r['resolved_at'] else None)
                    for r in rows],
        'count': len(rows),
        'unresolved': unresolved,
    }
