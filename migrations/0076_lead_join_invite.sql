-- 0076_lead_join_invite.sql
-- One invitation to join per address, across all gatherings (TEC-1845,
-- docs/superpowers/plans/2026-10-22-events-invite-to-join.md). Kept while
-- Ahavah holds any lead row for the address; the lead retention sweep
-- deletes it with the last one, as the privacy page's 12 months say.
--
-- Additive and idempotent: the deploy applies it once
-- (scripts/apply-deploy-migrations.sh) and the test fixtures at every
-- session start. A new table, so nothing busy is locked.
CREATE TABLE IF NOT EXISTS lead_join_invite (
  normalized_email  TEXT         PRIMARY KEY,
  event_id          BIGINT       REFERENCES event(id) ON DELETE SET NULL,
  invited_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
