"""Unfinished sign-ups (TEC-1897; frames U.1 to U.4).

An `onboardee` row exists from the first sign-in code until the person
finishes, signs in again more than an hour after their last save, or saves
nothing for a week (the garbage cron). So this lists people who stopped
within the last 7 days. Only steps the server stores can be the furthest
step; verify email, verify phone, marital status, children and looking for
leave no server record during sign-up. Dates and a step only: no name and
no address leave the server.
"""
from __future__ import annotations

# In the web's order (ahavah-web src/lib/wizard-flow.ts), limited to the
# steps the server records. 'none' is someone who signed in and saved
# nothing, which the design calls "The first step".
STEPS = ('none', 'name', 'date_of_birth', 'gender', 'photos', 'country', 'assembly', 'relocation')

_STEP = """
    CASE
      WHEN o.ahavah_extra ? 'relocation' THEN 'relocation'
      WHEN o.ahavah_extra ? 'assembly' THEN 'assembly'
      WHEN o.coordinates IS NOT NULL THEN 'country'
      WHEN EXISTS (SELECT 1 FROM onboardee_photo ph WHERE ph.email = o.email) THEN 'photos'
      WHEN o.gender_id IS NOT NULL THEN 'gender'
      WHEN o.date_of_birth IS NOT NULL THEN 'date_of_birth'
      WHEN o.name IS NOT NULL THEN 'name'
      ELSE 'none'
    END
"""

Q_UNFINISHED = f"""
    WITH o AS (
        SELECT o.created_at, o.updated_at, o.lead_source, {_STEP} AS furthest_step
          FROM onboardee o
         WHERE NOT EXISTS (SELECT 1 FROM person p WHERE lower(p.email) = lower(o.email))
           AND lower(o.email) <> ALL(%(ex)s)
           AND o.updated_at < NOW() - INTERVAL '1 hour'
    )
    SELECT created_at AS started_at, updated_at AS last_saved_at, furthest_step
      FROM o
     WHERE lead_source IS NULL OR furthest_step <> 'none'
     ORDER BY created_at DESC
     LIMIT 200
"""
