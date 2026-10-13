-- 0060_onboarding_first_touch.sql
-- Where a member came from (health review, 13 Oct 2026, finding 42).
--
-- 26 of 27 members who joined since August have no source. The web now
-- keeps the first touch on the visitor's device (UTM values, the referring
-- host, an invite code, when) and sends it with POST /finish-onboarding,
-- with the optional answer to "How did you hear about Ahavah?".
--
--   person.first_touch: the accepted first-touch values, as sent (NULL when
--     none were sent or none were accepted).
--   person.heard_about: the answer, at most 200 characters (NULL when none).
--
-- person.lead_source (0032) is written from them at onboarding; see
-- service/person/attribution.py. First-party only, never shared.
--
-- Idempotent (IF NOT EXISTS).

ALTER TABLE person ADD COLUMN IF NOT EXISTS first_touch JSONB;
ALTER TABLE person ADD COLUMN IF NOT EXISTS heard_about TEXT;
