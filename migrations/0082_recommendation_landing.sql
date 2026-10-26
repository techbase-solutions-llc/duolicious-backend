-- 0082_recommendation_landing.sql
-- The recommended single's landing page (TEC-1845; ahavah-web
-- docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 7, release 3).
--
-- The recommendation email now links to a short page that names who
-- recommended them (first name) and shows their note, in place of going
-- straight to the sign-up form. The link carries a token; only its sha256
-- is kept here, as for every other emailed link. A row without one (sent
-- before this, or while the page was switched off) keeps its old link.
--
-- Additive and idempotent: the deploy applies it once
-- (scripts/apply-deploy-migrations.sh) and the test fixtures at every
-- session start. Each statement waits at most 5 seconds for its lock on
-- recommendation; if it gives up, the migration stops with an error and
-- can simply be run again. Never edit this file once it has shipped.
SET lock_timeout = '5s';

ALTER TABLE recommendation ADD COLUMN IF NOT EXISTS landing_token_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx__recommendation__landing_token_hash
  ON recommendation (landing_token_hash) WHERE landing_token_hash IS NOT NULL;

RESET lock_timeout;
