"""Unfinished sign-ups (TEC-1897; frames U.1 to U.4).

An `onboardee` row exists from the first sign-in code until the person
finishes, signs in again more than an hour after their last save, or saves
nothing for a week (the garbage cron). So this lists people who stopped
within the last 7 days. Only steps the server stores can be the furthest
step; verify email, verify phone, marital status, children and looking for
leave no server record during sign-up. Dates and a step only: no name and
no address leave the server.

Q_UNFINISHED reads each address so the route can look up the unfinished
sign-up reminder (TEC-2107, emails/unfinished_signup.py reminder_states);
the route drops it before answering.
"""
from __future__ import annotations

from typing import Optional

# In the web's order (ahavah-web src/lib/wizard-flow.ts), limited to the
# steps the server records. 'none' is someone who signed in and saved
# nothing, which the design calls "The first step".
STEPS = ('none', 'name', 'date_of_birth', 'gender', 'photos', 'country', 'assembly', 'relocation')

# The lead_email_send campaign of the unfinished sign-up reminder (TEC-2107).
REMINDER_CAMPAIGN = 'unfinished_signup'


def claim_key(email: Optional[str]) -> Optional[str]:
    """The reminder's claim key in lead_email_send.email: a keyed hash
    (service.matchmaker.address_key, HMAC-SHA256 with the unsubscribe
    secret) of the lower-cased address, never the address. The onboardee
    row goes after a week; the claim stays so the address is never
    reminded twice, and it cannot be read back as an address."""
    if not email or not email.strip():
        return None
    from service.matchmaker import address_key
    return address_key(email.strip().lower())

STEP_SQL = """
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
        SELECT o.created_at, o.updated_at, o.lead_source, {STEP_SQL} AS furthest_step,
               lower(o.email) AS email
          FROM onboardee o
         WHERE NOT EXISTS (SELECT 1 FROM person p WHERE lower(p.email) = lower(o.email))
           AND lower(o.email) <> ALL(%(ex)s)
           AND o.updated_at < NOW() - INTERVAL '1 hour'
    )
    SELECT created_at AS started_at, updated_at AS last_saved_at, furthest_step, email
      FROM o
     WHERE lead_source IS NULL OR furthest_step <> 'none'
     ORDER BY created_at DESC
     LIMIT 200
"""
