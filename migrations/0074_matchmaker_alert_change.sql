-- 0074_matchmaker_alert_change.sql
-- Matchmaker (TEC-1845), the pre-launch review of 21 Oct. Needs 0073.
--
-- Anyone can type a visitor's address into the alert form, so a confirmed
-- visitor alert no longer changes when the form is sent again. The new
-- criteria and first name wait here, and a confirm link goes to the
-- address; they replace the alert's only when that link is used. Only the
-- newest link applies (change_token_hash, its sha256). The link's expiry
-- and the count of links sent reuse confirm_by and resends, which a
-- confirmed alert no longer needs.
--
-- match_alert is a small table that only the matchmaker uses, still dark,
-- but each statement waits at most 5 seconds for its lock all the same.
-- Every statement is idempotent.
SET lock_timeout = '5s';

ALTER TABLE match_alert
  ADD COLUMN IF NOT EXISTS pending_criteria    JSONB,
  ADD COLUMN IF NOT EXISTS pending_first_name  TEXT CHECK (char_length(pending_first_name) BETWEEN 1 AND 40),
  ADD COLUMN IF NOT EXISTS change_token_hash   TEXT UNIQUE;

RESET lock_timeout;
