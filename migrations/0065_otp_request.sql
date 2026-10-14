-- 0065_otp_request.sql
-- One row per sign-in code request, so Admin > System can show codes
-- requested and never entered per day, split into new and existing
-- addresses (TEC-1848, docs/superpowers/plans/2026-10-13-free-signup-bot-
-- protection.md, item 6).
--
-- duo_session cannot answer that question on its own: it has no creation
-- time, and /request-otp deletes an address's earlier unsigned sessions
-- every time a new code is asked for.
--
--   new_address         the address had no account when the code was asked for
--   refused             NULL when a code was issued; otherwise why the server
--                       sent nothing and answered as though it had (honeypot,
--                       timing stamp, new-address limits, undeliverable domain)
--   session_token_hash  the pending session the code belongs to, so /check-otp
--                       can mark it entered; cleared once it is
--   entered_at          when that session was signed in
--
-- No email address is stored.
--
-- Idempotent: the deploy may run this file more than once.

CREATE TABLE IF NOT EXISTS otp_request (
  id                  BIGSERIAL    PRIMARY KEY,
  requested_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  new_address         BOOLEAN      NOT NULL,
  refused             TEXT,
  session_token_hash  TEXT,
  entered_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx__otp_request__requested_at
  ON otp_request (requested_at);

CREATE INDEX IF NOT EXISTS idx__otp_request__session_token_hash
  ON otp_request (session_token_hash)
  WHERE session_token_hash IS NOT NULL;
