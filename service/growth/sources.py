"""The Sources table on the Growth tab (growth spec, Dashboard; TEC-1845).

One row per source on the taxonomy (service/leads/sources.py): the leads it
brought and how many confirmed, the members who signed up from it, and how
many of those reached a conversation both people have written in. Members
are counted as the rest of the Growth tab counts them: activated, not
staff, not a test address. Message content is never read; conversations
come from the same _SENT_MESSAGES the Overview uses.
"""
from __future__ import annotations

from service.admin.queries.engagement import _SENT_MESSAGES
from service.admin.queries.members import member_sql
from service.growth.queries import _excluded
from service.leads.sources import source_kind

_Q_SOURCES = f"""
    WITH members AS (
        SELECT p.id, COALESCE(p.lead_source, 'unknown') AS source
          FROM person p
         WHERE p.activated AND {member_sql('p')} AND lower(p.email) <> ALL(%(ex)s)
    ),
    sent AS ({_SENT_MESSAGES}),
    answered AS (
        SELECT lo, hi FROM sent GROUP BY lo, hi HAVING count(DISTINCT sender_id) >= 2
    ),
    conversed AS (
        SELECT lo AS id FROM answered UNION SELECT hi FROM answered
    ),
    signups AS (
        SELECT m.source, count(*) AS signups,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM conversed c WHERE c.id = m.id)) AS conversed
          FROM members m
         GROUP BY m.source
    ),
    leads AS (
        SELECT source, count(*) AS leads,
               count(*) FILTER (WHERE confirmed_at IS NOT NULL) AS confirmed_leads
          FROM lead
         GROUP BY source
    )
    SELECT COALESCE(s.source, l.source)        AS source,
           COALESCE(l.leads, 0)::int            AS leads,
           COALESCE(l.confirmed_leads, 0)::int  AS confirmed_leads,
           COALESCE(s.signups, 0)::int          AS signups,
           COALESCE(s.conversed, 0)::int        AS conversed
      FROM signups s
      FULL OUTER JOIN leads l ON l.source = s.source
     ORDER BY signups DESC, leads DESC, source
"""


def source_rows(tx) -> list[dict]:
    rows = tx.execute(_Q_SOURCES, dict(ex=_excluded())).fetchall()
    return [dict(r, kind=source_kind(None if r['source'] == 'unknown' else r['source']))
            for r in rows]
