-- 0076_lead_join_invite.sql
-- One invitation to join per address, across all gatherings (TEC-1845,
-- docs/superpowers/plans/2026-10-22-events-invite-to-join.md). Kept while
-- Ahavah holds any lead row for the address; the lead retention sweep
-- deletes it with the last one, as the privacy page's 12 months say.
--
-- Additive and idempotent: the deploy applies it once
-- (scripts/apply-deploy-migrations.sh) and the test fixtures at every
-- session start. The table is new, but its foreign key takes a SHARE ROW
-- EXCLUSIVE lock on event, which waits for any open write on event (an
-- organiser's edit, an admin's pause) and holds every later one behind
-- it. So the statement waits at most 5 seconds for that lock, as 0077
-- does; if it gives up, the migration stops with an error (ON_ERROR_STOP)
-- and, being idempotent, can simply be run again.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS lead_join_invite (
  normalized_email  TEXT         PRIMARY KEY,
  event_id          BIGINT       REFERENCES event(id) ON DELETE SET NULL,
  invited_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

RESET lock_timeout;
