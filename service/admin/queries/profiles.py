"""Verification tiers, profile gaps, the photo gate list and approved photos
with no face (TEC-1897; frames G.1, P.1, P.2 and P.3).

CONTENT IS NEVER READ: the gate list counts a member's sent messages from
mam_message's id, direction and person only.
"""
from __future__ import annotations

from service.admin.queries.members import counted_member_sql, member_sql

TIERS = ('none', 'bronze', 'silver', 'gold')

Q_VERIFICATION_TIERS = f"""
    SELECT t.tier, count(p.id)::int AS members
      FROM unnest(ARRAY['none', 'bronze', 'silver', 'gold']) WITH ORDINALITY AS t(tier, ord)
      LEFT JOIN person p
        ON p.ahavah_verification_tier::text = t.tier AND {counted_member_sql('p')}
     GROUP BY t.tier, t.ord
     ORDER BY t.ord
"""
