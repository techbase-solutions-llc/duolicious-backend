"""SQL for the Audit Log tab, a filterable view of admin_audit_log.

TEC-1845 admin audit: days 0 is all time, as on the ledger (it matched
nothing, since `created_at > NOW() - '0 days'`). Target matches any part of
the address in any case; actor the whole address in any case, since the
admin offers actors from a list; action stays exact. `target_like` is
`%<target>%` with LIKE's own wildcards escaped by the route."""

_WHERE = """
     WHERE (%(actor)s = '' OR lower(actor_email) = lower(%(actor)s))
       AND (%(target)s = '' OR target_email ILIKE %(target_like)s)
       AND (%(action)s = '' OR action = %(action)s)
       AND (%(days)s = 0 OR created_at > NOW() - make_interval(days => %(days)s))
"""

Q_AUDIT_LIST = f"""
    SELECT
        -- The row's id, so "See the audit entry" can open this row.
        id::text AS id,
        actor_email, actor_uuid::text AS actor_uuid,
        action, target_email, target_uuid::text AS target_uuid,
        metadata, created_at
      FROM admin_audit_log
    {_WHERE}
     ORDER BY created_at DESC
     LIMIT %(limit)s OFFSET %(offset)s
"""

Q_AUDIT_COUNT = f"""
    SELECT COUNT(*) AS total
      FROM admin_audit_log
    {_WHERE}
"""

# Every actor and action on file, all time, for the design's actor dropdown
# and action pills.
Q_AUDIT_ACTORS = """
    SELECT DISTINCT actor_email FROM admin_audit_log ORDER BY actor_email LIMIT 500
"""

Q_AUDIT_ACTIONS = """
    SELECT DISTINCT action FROM admin_audit_log ORDER BY action LIMIT 500
"""
