"""Push subscribers for Growth (TEC-1897; frame G.1).

A member has push on while at least one push_subscription row is theirs.
Rows the push service refuses are deleted (migration 0030), so "new since"
counts members whose oldest surviving subscription is that recent. Binds
%(ex)s and %(since)s (a Barbados date).
"""
from __future__ import annotations

from service.admin.queries.members import counted_member_sql

# The Discover banner that asks members to turn push on shipped on 1 Oct
# 2026 (design brief, section 6), so the tile counts from that day.
PUSH_BANNER_SHIPPED = '2026-10-01'

Q_PUSH = f"""
    WITH m AS (
        SELECT p.id,
               (SELECT min(ps.created_at) FROM push_subscription ps WHERE ps.person_id = p.id) AS first_sub,
               EXISTS (SELECT 1 FROM push_subscription ps
                        WHERE ps.person_id = p.id AND ps.consecutive_failures > 0) AS failing
          FROM person p
         WHERE {counted_member_sql('p')}
    )
    SELECT count(*)::int                                          AS members,
           count(*) FILTER (WHERE first_sub IS NOT NULL)::int     AS members_with_push,
           count(*) FILTER (WHERE failing)::int                   AS members_failing,
           count(*) FILTER (WHERE first_sub >=
               (%(since)s::date::timestamp AT TIME ZONE 'America/Barbados'))::int AS members_new_since,
           (SELECT count(DISTINCT ps.person_id) FROM push_subscription ps
              JOIN person p ON p.id = ps.person_id WHERE p.activated)::int AS with_push_counting_staff
      FROM m
"""
