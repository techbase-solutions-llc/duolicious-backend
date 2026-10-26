-- 0085_address_session.sql
-- The light sign-in, "Your Ahavah" (TEC-1845; ahavah-web docs/plans/
-- 2026-10-22-in-app-entry-and-sign-up.md, section 5 and release 4).
--
-- A short-lived ADDRESS session: proof that the caller holds an inbox, for
-- organisers, mentors, recommenders and gathering guests who are not
-- members. It is kept apart from duo_session on purpose. A duo_session row
-- is what every member route reads (service/api/decorators.py), so a token
-- that lives only here can never open a member route, and asking for one
-- never creates or deletes the half-finished sign-up record (onboardee).
--
-- One row per code asked for:
--   request_token_hash  sha256 of the handle the web holds between the two
--                       steps (the code alone is only 6 digits)
--   code_hash           sha256 of the code with the handle; NULL once used,
--                       so a code works once
--   code_expires_at     10 minutes after it was asked for
--   code_attempts       wrong codes; the code dies at 5
--   session_token_hash  sha256 of the address session's token, once the
--                       code was right; sent back as X-Address-Token
--   session_expires_at  60 minutes after the code was entered
--
-- The address is kept only while the row lives: the lead retention cron
-- deletes a row a day after its code or its session lapsed, and "delete
-- everything" deletes every row of the address.
--
-- Idempotent; waits at most 5 seconds for a lock.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS address_session (
  id                  BIGSERIAL    PRIMARY KEY,
  email               TEXT         NOT NULL,
  normalized_email    TEXT         NOT NULL,
  request_token_hash  TEXT         NOT NULL UNIQUE,
  code_hash           TEXT,
  code_expires_at     TIMESTAMPTZ  NOT NULL,
  code_attempts       INT          NOT NULL DEFAULT 0,
  session_token_hash  TEXT         UNIQUE,
  session_expires_at  TIMESTAMPTZ,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx__address_session__normalized_email
  ON address_session (normalized_email);

RESET lock_timeout;
